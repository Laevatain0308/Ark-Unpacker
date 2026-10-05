"""Structural fixtures plus an optional real-bundle acceptance test.

ARK_SHADER_SAMPLE=/path/to/stylizedwater.ab python -m unittest discover -s test -p test_shader_programs.py -v
"""
import hashlib
import itertools
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace as NS

import lz4.block
import UnityPy
import src.ResolveAB  # register Arknights bundle decompression
from src.ResolveAB import ResolveABWorkerSession
from src.ShaderPrograms import collect_shader_programs, export_directory
from src.mp.FsGuardProcess import _FsGuardRuntime, FsGuardClient
from src.mp.Messages import PrepareWriteRequest
from src.utils.SaverUtils import SafeSaver


def integer(value):
    return struct.pack('<i', value)


def string(value):
    data = value.encode('utf8')
    return integer(len(data)) + data + bytes((-len(data)) % 4)


def program(code, keywords=(), version=202012090, gpu_type=4, local_keywords=()):
    data = integer(version) + integer(gpu_type) + bytes(12)
    if version >= 201608170:
        data += bytes(4)
    data += integer(len(keywords)) + b''.join(string(x) for x in keywords)
    if 201806140 <= version < 202012090:
        data += integer(len(local_keywords)) + b''.join(string(x) for x in local_keywords)
    data += integer(len(code)) + code
    return data + bytes((-len(data)) % 4)


COMBINED = b'#ifdef VERTEX\nvoid main() { gl_Position = vec4(0.0); }\n#endif\n#ifdef FRAGMENT\nvoid main() {}\n#endif\n'


def shader_fixture(entries, references, version=(2021, 3, 39), segments=1, flattened=False):
    # entries: (segment, serialized program bytes). Entry offsets are relative
    # to their own decompressed segment, not to concatenated platform bytes.
    size = 12 if version >= (2019, 3) else 8
    data = [bytearray() for _ in range(segments)]
    data[0] = bytearray(integer(len(entries)) + bytes(size * len(entries)))
    table = bytearray(integer(len(entries)))
    for segment, entry in entries:
        offset = len(data[segment])
        data[segment].extend(entry)
        table.extend(integer(offset) + integer(len(entry)))
        if size == 12:
            table.extend(integer(segment))
    data[0][:len(table)] = table
    blob, offsets, clens, dlens = bytearray(), [], [], []
    for raw in data:
        compressed = lz4.block.compress(bytes(raw), store_size=False)
        offsets.append(len(blob)); clens.append(len(compressed)); dlens.append(len(raw))
        blob.extend(compressed)
    vertex = NS(m_SubPrograms=references, m_PlayerSubPrograms=None)
    pa = NS(progVertex=vertex, m_Name='Main', m_Type=0, m_State=NS(m_Name='Main'))
    parsed = NS(m_Name='Fixture/Shader', m_SubShaders=[NS(m_Passes=[pa])],
                m_KeywordNames=['DEPTH', 'COPY'] if version >= (2021, 2) else None,
                m_KeywordFlags=[0, 0] if version >= (2021, 2) else None)
    row = lambda x: [x[0]] if flattened else [x]
    return NS(m_Name='', m_ParsedForm=parsed, platforms=[9], compressedBlob=bytes(blob),
              offsets=row(offsets), compressedLengths=row(clens), decompressedLengths=row(dlens),
              object_reader=NS(version=version, path_id=17, assets_file=NS(name='CAB-fixture', unity_version='.'.join(map(str,version)))))


def reference(blob_index, indices=(), gpu_type=4, **kw):
    return NS(m_BlobIndex=blob_index, m_GpuProgramType=gpu_type, m_KeywordIndices=list(indices), **kw)


class ShaderProgramTests(unittest.TestCase):
    def collect(self, shader):
        return collect_shader_programs(shader, '/fixtures/bundle.ab')

    def test_multiple_segments_shared_program_and_complete_combined_payload(self):
        s = shader_fixture([(1, program(COMBINED, ['DEPTH'])), (0, program(COMBINED))],
                           [reference(0, [0]), reference(0, [0,1]), reference(1)], segments=2)
        s.m_ParsedForm.m_SubShaders[0].m_Passes.append(s.m_ParsedForm.m_SubShaders[0].m_Passes[0])
        m, payloads = self.collect(s)
        records = m['platforms'][0]['programs']
        self.assertEqual(len(payloads), 2)
        self.assertEqual(records[0]['segment'], 1)
        self.assertEqual(records[0]['offset'], 0)
        self.assertEqual(len(records[0]['references']), 4)
        self.assertEqual({r['pass_index'] for r in records[0]['references']}, {0, 1})
        self.assertEqual(records[0]['references'][0]['keywords'], ['DEPTH'])
        self.assertEqual(records[0]['references'][1]['keywords'], ['DEPTH','COPY'])
        self.assertEqual(records[0]['payload_stage'], 'combined')
        self.assertEqual(payloads[0][2], COMBINED)
        self.assertEqual(records[0]['sha256'], hashlib.sha256(COMBINED).hexdigest())

    def test_defined_guards_and_position_do_not_confuse_stage(self):
        code=b'#if defined(VERTEX) || defined(FRAGMENT)\nvoid main() { gl_Position = vec4(0.0); }\n#endif\n'
        shader=shader_fixture([(0,program(code))],[])
        _,payloads=self.collect(shader)
        self.assertEqual(payloads[0][0]['payload_stage'],'combined')
        shader=shader_fixture([(0,program(b'void main() { gl_Position = vec4(0.0); }'))],[])
        _,payloads=self.collect(shader)
        self.assertEqual(payloads[0][0]['payload_stage'],'unknown')

    def test_player_subprograms_and_parameter_entries(self):
        s = shader_fixture([(0, b'not a program'), (0, program(COMBINED, ['DEPTH']))], [])
        pr = s.m_ParsedForm.m_SubShaders[0].m_Passes[0].progVertex
        pr.m_PlayerSubPrograms = [[], [reference(1,[0]), reference(1,[0])]]
        pr.m_ParameterBlobIndices = [[], [0,0]]
        m, payloads = self.collect(s)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(len(m['platforms'][0]['parameter_entries']), 1)
        self.assertEqual(len(payloads[0][0]['references']), 2)
        self.assertEqual(payloads[0][0]['references'][0]['player_group_index'], 1)

    def test_pre_2019_3_flat_arrays_and_embedded_keywords(self):
        s = shader_fixture([(0, program(COMBINED, ['GLOBAL'], version=201806140, local_keywords=['LOCAL']))],
                           [reference(0, m_GlobalKeywordIndices=[3], m_LocalKeywordIndices=[2])],
                           version=(2019,2,0), flattened=True)
        m, payloads = self.collect(s)
        r = payloads[0][0]
        self.assertEqual(r['segment'], 0)
        self.assertEqual(r['program_keywords'], ['GLOBAL'])
        self.assertEqual(r['program_local_keywords'], ['LOCAL'])
        self.assertNotIn('keywords',r['references'][0])  # no invented index/name mapping

    def test_2019_to_2021_1_global_local_indices(self):
        s = shader_fixture([(0, program(COMBINED, ['GLOBAL'], version=201806140, local_keywords=['LOCAL']))],
                           [reference(0, m_GlobalKeywordIndices=[3], m_LocalKeywordIndices=[2])],version=(2020,3,0))
        _, payloads = self.collect(s)
        ref = payloads[0][0]['references'][0]
        self.assertEqual(ref['m_GlobalKeywordIndices'], [3])
        self.assertEqual(ref['m_LocalKeywordIndices'], [2])
        self.assertEqual(ref['program_local_keywords'], ['LOCAL'])

    def test_program_failure_isolated_and_never_truncated(self):
        truncated = program(COMBINED)[:-20]
        s = shader_fixture([(0,truncated),(0,program(COMBINED))],[reference(0),reference(1)])
        m, payloads = self.collect(s)
        self.assertEqual(len(payloads),1)
        self.assertEqual(m['platforms'][0]['programs'][0]['status'],'failed')
        self.assertIn('exceeds entry bounds',m['platforms'][0]['programs'][0]['diagnostics'][0]['reason'])
        self.assertEqual(payloads[0][0]['blob_index'],1)

    def test_bad_segment_does_not_lose_good_segment(self):
        s = shader_fixture([(1,program(COMBINED)),(0,program(COMBINED))],[],segments=2)
        s.offsets[0][1] = len(s.compressedBlob)+100
        m,payloads=self.collect(s)
        self.assertEqual(len(payloads),1)
        self.assertEqual(payloads[0][0]['blob_index'],1)
        self.assertEqual(m['platforms'][0]['segments'][1]['diagnostics'][0]['code'],'decompression_failed')

    def test_unknown_format_and_invalid_keyword_indices_are_diagnosed(self):
        s=shader_fixture([(0, program(COMBINED,version=209999999)),(0,program(COMBINED))],
                         [reference(0),reference(1,[99])])
        m,payloads=self.collect(s)
        self.assertEqual(len(payloads),1)
        self.assertIn('unsupported program serialization version',m['platforms'][0]['programs'][0]['diagnostics'][0]['reason'])
        self.assertEqual(payloads[0][0]['references'][0]['keyword_resolution'],'partial')

    def test_ambiguous_platform_association_is_not_invented(self):
        shader=shader_fixture([(0,program(b'console payload',gpu_type=26))],[reference(0,gpu_type=26)])
        shader.platforms=[11,12]
        shader.offsets *= 2; shader.compressedLengths *= 2; shader.decompressedLengths *= 2
        manifest,payloads=self.collect(shader)
        self.assertEqual(len(payloads),2)
        self.assertEqual(payloads[0][0]['references'],[])
        self.assertEqual(manifest['unresolved_references'][0]['diagnostics'][0]['code'],'ambiguous_platform')

    def test_vulkan_is_exact_binary_even_if_contains_text(self):
        raw=b'\x00\xffSPIRV-wrapper'+COMBINED
        s=shader_fixture([(0,program(raw,gpu_type=25))],[reference(0,gpu_type=25)])
        s.platforms=[18]
        m,ps=self.collect(s)
        self.assertEqual(ps[0][2],raw)
        self.assertTrue(ps[0][1].endswith('.bin'))
        self.assertEqual(ps[0][0]['content_type'],'unity-vulkan-payload')

    def test_bad_table_unsupported_legacy_and_missing_entry(self):
        s=shader_fixture([(0,program(COMBINED))],[reference(9)])
        m,ps=self.collect(s)
        self.assertEqual(m['platforms'][0]['diagnostics'][0]['code'],'blob_index_out_of_range')
        s.compressedLengths[0].append(1)
        m,_=self.collect(s)
        self.assertEqual(m['platforms'][0]['diagnostics'][0]['code'],'invalid_segment_arrays')
        s.platforms=[]
        m,_=self.collect(s)
        self.assertEqual(m['diagnostics'][0]['code'],'unsupported_blob_layout')

    def test_stable_safe_directory(self):
        source={'bundle':'/one.ab','cab':'CAB-a','path_id':1}
        a=export_directory('../a:b*c?d',source)
        self.assertNotIn('/',a)
        self.assertNotIn(':',a)
        self.assertEqual(a,export_directory('../a:b*c?d',source))
        self.assertNotEqual(a,export_directory('../a:b*c?d',{**source,'cab':'CAB-b'}))

    def test_write_failure_and_shader_read_failure_keep_diagnostic_manifests(self):
        shader=shader_fixture([(0,program(COMBINED)),(0,program(COMBINED))],[])
        reader=shader.object_reader
        reader.read=lambda:shader
        with tempfile.TemporaryDirectory() as tmp:
            reporter=NS(log=lambda *args:None,file_saved=lambda *args:None)
            guard=NS(prepare_write_response=lambda target,filename,ext,h:
                     NS(approved=True,path=str(Path(tmp)/filename)))
            session=ResolveABWorkerSession(reporter,guard,'utf-8',2)
            manifests=[]
            session.save_json=lambda m,*args:manifests.append(m)
            real_write=SafeSaver.write_data
            def write(path,data):
                if 'blob000000' in path:
                    raise OSError('fixture write failure')
                real_write(path,data)
            with patch.object(SafeSaver,'write_data',side_effect=write):
                session.save_shader_programs(reader,'fixture.ab',tmp)
            records=manifests[-1]['platforms'][0]['programs']
            self.assertEqual(records[0]['status'],'failed')
            self.assertEqual(records[0]['diagnostics'][0]['code'],'program_write_failed')
            self.assertEqual(records[1]['status'],'exported')
            def broken_read():
                raise ValueError('unreadable Shader')
            reader.read=broken_read
            session.save_shader_programs(reader,'fixture.ab',tmp)
            self.assertEqual(manifests[-1]['diagnostics'][0]['code'],'shader_parse_failed')
            self.assertNotIn('shader_name',manifests[-1])

    def test_platform_decompression_failure_does_not_abort_other_platform(self):
        shader=shader_fixture([(0,program(COMBINED))],[reference(0)])
        shader.platforms=[9,18]
        shader.offsets.append([len(shader.compressedBlob)+1])
        shader.compressedLengths.append([20]); shader.decompressedLengths.append([40])
        manifest,payloads=self.collect(shader)
        self.assertEqual(len(payloads),1)
        self.assertEqual(manifest['platforms'][1]['diagnostics'][0]['code'],'entry_table_failed')

    def test_fs_guard_collision_reuse_links_real_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'program.glsl').write_bytes(b'old')
            responses=queue.Queue(); logs=NS(log=lambda *args:None)
            sender=NS(create_reporter=lambda:logs)
            runtime=_FsGuardRuntime([responses],sender)
            h=SafeSaver.hash_data(b'new')
            request=PrepareWriteRequest(0,0,tmp,'program','.glsl',h)
            runtime._prepare_write(request)
            first=responses.get()
            self.assertTrue(first.approved)
            self.assertEqual(Path(first.path).name,'program$0.glsl')
            Path(first.path).write_bytes(b'new')
            runtime._prepare_write(request)
            second=responses.get()
            self.assertFalse(second.approved)
            self.assertEqual(second.path,first.path)
            # Existing callers keep the historical None-on-dedup behavior.
            client=FsGuardClient(queue.Queue(),queue.Queue(),0)
            client._request=lambda _:second
            self.assertIsNone(client.prepare_write(tmp,'program','.glsl',h))
            self.assertEqual(client.prepare_write_response(tmp,'program','.glsl',h).path,first.path)


@unittest.skipUnless(os.environ.get('ARK_SHADER_SAMPLE'), 'Set ARK_SHADER_SAMPLE for the real-bundle acceptance test')
class StylizedWaterAcceptance(unittest.TestCase):
    def test_sample_full_payloads_variants_and_shader_regression(self):
        sample=os.environ['ARK_SHADER_SAMPLE']
        shader=next(r.read() for r in UnityPy.load(sample).objects
                    if r.type.name=='Shader' and r.read().m_ParsedForm.m_Name=='Torappu/Scene/StylizedWater')
        original=shader.export().encode('utf-8','surrogateescape')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp,'output')
            args=[sys.executable,'Main.py','-m','ab','-i',sample,'-o',str(out),'--shader-programs']
            subprocess.run(args,check=True,capture_output=True)
            path=next(out.rglob('manifest.json'))
            manifest=json.loads(path.read_text())
            self.assertEqual(manifest['unity_version'],'2021.3.39f1')
            self.assertFalse(list(out.rglob('*.shaderlab.txt')))
            gl=next(p for p in manifest['platforms'] if p['value']==9)
            vk=next(p for p in manifest['platforms'] if p['value']==18)
            self.assertEqual(len(gl['programs']),32)
            self.assertEqual({r['blob_index'] for r in gl['programs']},set(range(24,56)))
            self.assertEqual(len(vk['programs']),32)
            combos=set()
            from UnityPy.helpers import CompressionHelper
            # Cross-check each file against the exact declared byte range in the
            # decompressed platform data, independent of filesystem export.
            for platform in (gl,vk):
                pi=platform['platform_index']
                raw=CompressionHelper.decompress_lz4(bytes(shader.compressedBlob)[shader.offsets[pi][0]:shader.offsets[pi][0]+shader.compressedLengths[pi][0]],shader.decompressedLengths[pi][0])
                for record in platform['programs']:
                    self.assertEqual(record['status'],'exported')
                    self.assertNotIn('diagnostics',record)
                    data=(path.parent/record['file']).read_bytes()
                    start=record['code_offset_in_segment']
                    self.assertEqual(data,raw[start:start+record['code_length']])
                    self.assertEqual(hashlib.sha256(data).hexdigest(),record['sha256'])
                    ref=record['references'][0]
                    self.assertNotIn('diagnostics',ref)
                    self.assertEqual(set(ref['keywords']),set(record['program_keywords']))
                    if platform is vk:
                        self.assertEqual(record['content_type'],'unity-vulkan-payload')
                        self.assertTrue(record['file'].endswith('.bin'))
                        continue
                    self.assertEqual(record['payload_stage'],'combined')
                    text=data.decode('utf8')
                    keys=set(ref['keywords']); combos.add(frozenset(keys))
                    self.assertIn('#ifdef VERTEX',text); self.assertIn('#ifdef FRAGMENT',text)
                    depth='HG_WATER_DEPTH' in keys; copy='_HGCOPYDEPTH' in keys
                    self.assertEqual('_HGWaterDepthTex' in text,depth and not copy)
                    self.assertEqual('_CameraDepthTexture' in text,depth and copy)
                    self.assertEqual('_HGUnderWaterTex' in text,'HG_WATER_DISTORT' in keys)
            expected = {frozenset([sun] + [key for key,enabled in zip(
                ['HG_WATER_DEPTH','HG_WATER_DISTORT','HG_WATER_SIMPLE','_HGCOPYDEPTH'],flags) if enabled])
                for sun in ['_SUNMODE_DEFAULT','_SUNMODE_CUSTOM']
                for flags in itertools.product([False,True],repeat=4)}
            self.assertEqual(combos,expected)
            # Combined and independent modes preserve the existing export bytes.
            subprocess.run(args+['--shader'],check=True,capture_output=True)
            self.assertEqual(next(out.rglob('*.shaderlab.txt')).read_bytes(),original)
            subprocess.run(args,check=True,capture_output=True)  # existing files reused, manifest paths stay accurate
            self.assertEqual(len(list(out.rglob('*.glsl'))),32)
            self.assertEqual(len(list(out.rglob('*.bin'))),32)

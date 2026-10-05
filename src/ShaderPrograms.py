"""Export stored GPU payloads, keeping serialized variant references separate.

UnityPy 1.25's ShaderProgram ignores entry Segment/Length and also attempts to
parse parameter entries. Read its versioned table here, then use its existing
ShaderSubProgram parser on each bounded executable entry. Entry layout follows
AssetStudio's ShaderSubProgramEntry, not offsets discovered by scanning code.
Reference: https://github.com/Perfare/AssetStudio/blob/master/AssetStudioUtility/ShaderConverter.cs
"""
import hashlib
import os
import re
from collections import defaultdict

from UnityPy.enums import ShaderCompilerPlatform, ShaderGpuProgramType
from UnityPy.export.ShaderConverter import CheckGpuProgramUsable, ShaderSubProgram
from UnityPy.helpers import CompressionHelper
from UnityPy.streams import EndianBinaryReader

STAGES = {
    "progVertex": "vertex", "progFragment": "fragment", "progGeometry": "geometry",
    "progHull": "hull", "progDomain": "domain", "progRayTracing": "ray_tracing",
}
# These are the layouts supported by UnityPy's ShaderSubProgram parser.
PROGRAM_VERSIONS = {201509030, 201510240, 201608170, 201609010, 201708220, 201802150, 201806140, 202012090}
GL_TYPES = {
    ShaderGpuProgramType.kShaderGpuProgramGLLegacy,
    ShaderGpuProgramType.kShaderGpuProgramGLES31AEP,
    ShaderGpuProgramType.kShaderGpuProgramGLES31,
    ShaderGpuProgramType.kShaderGpuProgramGLES3,
    ShaderGpuProgramType.kShaderGpuProgramGLES,
    ShaderGpuProgramType.kShaderGpuProgramGLCore32,
    ShaderGpuProgramType.kShaderGpuProgramGLCore41,
    ShaderGpuProgramType.kShaderGpuProgramGLCore43,
}


def enum_info(enum, value):
    result = {"value": int(value)}
    try:
        result["name"] = enum(value).name
    except ValueError:
        pass
    return result


def source_info(reader, bundle):
    return {"bundle": os.path.realpath(bundle), "cab": reader.assets_file.name, "path_id": reader.path_id}


def export_directory(name, source):
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '#', name).strip(' .')
    safe = safe.encode('utf-8', 'surrogateescape')[:120].decode('utf-8', 'ignore') or 'Shader'
    identity = hashlib.sha256((source['bundle'] + '\0' + source['cab']).encode('utf-8')).hexdigest()[:12]
    return f"{safe}__{source['path_id']}__{identity}.programs"


def diagnostic(target, code, reason, **context):
    target.setdefault("diagnostics", []).append({"code": code, "reason": reason, **context})


class _BoundedReader:
    """Prevent UnityPy's permissive byte/string readers from silently truncating."""
    def __init__(self, data):
        self.reader = EndianBinaryReader(data, endian='<')
        self.payload_offset = None

    @property
    def Position(self):
        return self.reader.Position

    @Position.setter
    def Position(self, value):
        if not 0 <= value <= self.reader.Length:
            raise ValueError(f"position {value} outside entry length {self.reader.Length}")
        self.reader.Position = value

    def read_int(self):
        if self.Position + 4 > self.reader.Length:
            raise ValueError("integer extends past entry boundary")
        value = self.reader.read_int()
        if value < 0:
            raise ValueError(f"negative integer {value} in program/table header")
        return value

    def read_aligned_string(self):
        start = self.Position
        length = self.read_int()
        if length < 0 or length > self.reader.Length - self.Position:
            raise ValueError(f"keyword string length {length} exceeds entry bounds")
        self.Position = start
        value = self.reader.read_aligned_string()
        self.Position = self.reader.Position
        return value

    def read_byte_array(self):
        length = self.read_int()
        self.payload_offset = self.Position
        if length < 0 or length > self.reader.Length - self.Position:
            raise ValueError(f"program length {length} exceeds entry bounds")
        return self.reader.read_bytes(length)

    def align_stream(self):
        self.reader.align_stream()
        self.Position = self.reader.Position


def _keywords(ref, subprogram, parsed, version):
    if version >= (2021, 2):
        indices = getattr(subprogram, 'm_KeywordIndices', None)
        if indices is None:
            diagnostic(ref, 'missing_keyword_indices', 'm_KeywordIndices absent in unified keyword layout')
            return
        ref['keyword_indices'] = list(indices)
        names = getattr(parsed, 'm_KeywordNames', None)
        if names is None:
            diagnostic(ref, 'missing_keyword_table', 'SerializedShader.m_KeywordNames absent')
            return
        ref['keywords'] = [names[i] for i in indices if 0 <= i < len(names)]
        invalid = [i for i in indices if not 0 <= i < len(names)]
        ref['keyword_resolution'] = 'partial' if invalid else 'complete'
        if invalid:
            diagnostic(ref, 'keyword_index_out_of_range', 'Indices outside m_KeywordNames', indices=invalid)
    else:
        # Old layouts have global/local indices but no unified names table.
        # Keep the raw indices; names will come from the parsed program itself.
        fields = ('m_GlobalKeywordIndices', 'm_LocalKeywordIndices') if version >= (2019, 0) else ('m_KeywordIndices',)
        for field in fields:
            indices = getattr(subprogram, field, None)
            if indices is not None:
                ref[field] = list(indices)


def _references(parsed, platforms, version):
    refs = defaultdict(list)
    parameters = defaultdict(set)
    unresolved = []
    for si, subshader in enumerate(parsed.m_SubShaders):
        for pi, shader_pass in enumerate(subshader.m_Passes):
            for field, stage in STAGES.items():
                program = getattr(shader_pass, field, None)
                if program is None:
                    continue
                groups = [(None, getattr(program, 'm_SubPrograms', []) or [], None)]
                for gi, group in enumerate(getattr(program, 'm_PlayerSubPrograms', None) or []):
                    param_groups = getattr(program, 'm_ParameterBlobIndices', None) or []
                    groups.append((gi, group, param_groups[gi] if gi < len(param_groups) else None))
                for gi, group, param_group in groups:
                    for vi, subprogram in enumerate(group):
                        ref = {
                            'subshader_index': si, 'pass_index': pi, 'stage': stage,
                            'metadata_field': field, 'variant_index': vi,
                            'blob_index': subprogram.m_BlobIndex,
                            'gpu_program_type': enum_info(ShaderGpuProgramType, subprogram.m_GpuProgramType),
                        }
                        for key in ('m_Name', 'm_Type', 'm_UseName', 'm_TextureName'):
                            value = getattr(shader_pass, key, None)
                            if value is not None:
                                ref[key] = value
                        if getattr(shader_pass, 'm_State', None) is not None:
                            ref['pass_state_name'] = shader_pass.m_State.m_Name
                        if gi is not None:
                            ref['player_group_index'] = gi
                        for key in ('m_ShaderHardwareTier', 'm_ShaderRequirements'):
                            value = getattr(subprogram, key, None)
                            if value is not None:
                                ref[key] = value
                        if param_group is not None and vi < len(param_group):
                            ref['parameter_blob_index'] = param_group[vi]
                        _keywords(ref, subprogram, parsed, version)
                        candidates = []
                        for platform_index, platform in enumerate(platforms):
                            pass_platforms = getattr(shader_pass, 'm_Platforms', None)
                            if pass_platforms and platform not in pass_platforms:
                                continue
                            try:
                                usable = CheckGpuProgramUsable(platform, subprogram.m_GpuProgramType)
                            except (NotImplementedError, ValueError):
                                continue
                            if usable:
                                candidates.append(platform_index)
                        if len(candidates) == 1:
                            platform_index = candidates[0]
                            ref['platform_index'] = platform_index
                            refs[(platform_index, subprogram.m_BlobIndex)].append(ref)
                            if 'parameter_blob_index' in ref:
                                parameters[platform_index].add(ref['parameter_blob_index'])
                        elif candidates:
                            diagnostic(ref, 'ambiguous_platform', 'GPU type is compatible with multiple platforms; no unique serialized association',
                                       platform_indices=candidates)
                            unresolved.append(ref)
                        else:
                            diagnostic(ref, 'unmapped_platform', 'No supported platform matches the serialized GPU program type')
                            unresolved.append(ref)
    return refs, parameters, unresolved


def _segment_row(array, index):
    value = array[index]
    return list(value) if isinstance(value, (list, tuple)) else [value]


def read_entries(data, version):
    reader = _BoundedReader(data)
    count = reader.read_int()
    size = 12 if version >= (2019, 3) else 8
    if count < 0 or count > (len(data) - 4) // size:
        raise ValueError(f"entry count {count} exceeds program table bounds")
    entries = []
    for _ in range(count):
        entries.append({'offset': reader.read_int(), 'length': reader.read_int(),
                        'segment': reader.read_int() if size == 12 else 0})
    return entries


def _payload_type(program, refs):
    gpu_type = int(program.m_ProgramType)
    if gpu_type in GL_TYPES:
        text = bytes(program.m_ProgramCode).decode('utf-8')  # strict: never silently replace code
        # Only inspect conditional stage guards *after* structural payload parsing.
        guards = set()
        for macro, expression in re.findall(r'^\s*#\s*(?:ifdef\s+(\w+)|(?:if|elif)\s+([^\r\n]+))', text, re.M):
            if macro in ('VERTEX', 'FRAGMENT'):
                guards.add(macro)
            for parenthesized, bare in re.findall(r'\bdefined\s*(?:\(\s*(VERTEX|FRAGMENT)\s*\)|(VERTEX|FRAGMENT)\b)', expression):
                guards.add(parenthesized or bare)
        if guards == {'VERTEX', 'FRAGMENT'}:
            stage = 'combined'
        elif guards:
            stage = next(iter(guards)).lower()
        else:
            stage = 'unknown'
        return 'glsl', stage, '.glsl'
    # m_ProgramCode is the intact Unity platform payload, not necessarily a raw
    # SPIR-V module: Vulkan may include a Unity wrapper and SMOL-V compression.
    kind = 'unity-vulkan-payload' if gpu_type == 25 else 'unity-gpu-payload'
    return kind, 'unknown', '.bin'


def collect_shader_programs(shader, bundle):
    """Return manifest and (record, filename, exact payload bytes) for guarded saving."""
    reader = shader.object_reader
    version = tuple(reader.version)
    parsed = getattr(shader, 'm_ParsedForm', None)
    name = parsed.m_Name if parsed is not None else shader.m_Name
    manifest = {
        'schema_version': 1, 'shader_name': name,
        'unity_version': reader.assets_file.unity_version, 'source': source_info(reader, bundle),
        'platforms': [], 'unresolved_references': [], 'diagnostics': [],
    }
    if parsed is not None:
        for field in ('m_KeywordNames', 'm_KeywordFlags'):
            value = getattr(parsed, field, None)
            if value is not None:
                manifest[field] = list(value)
    platforms = list(getattr(shader, 'platforms', None) or [])
    refs, parameters, unresolved = _references(parsed, platforms, version) if parsed is not None else ({}, {}, [])
    manifest['unresolved_references'] = unresolved
    payloads = []
    blob = bytes(getattr(shader, 'compressedBlob', None) or [])
    if not platforms or not blob:
        diagnostic(manifest, 'unsupported_blob_layout', 'No platform compressedBlob; legacy script/subprogram blobs are not exported by this option')
        return manifest, payloads
    for index, platform_value in enumerate(platforms):
        platform = {'platform_index': index, **enum_info(ShaderCompilerPlatform, platform_value),
                    'segments': [], 'programs': [], 'parameter_entries': [], 'diagnostics': []}
        platform['variant_references'] = [ref for (platform_index, _), group in refs.items()
                                          if platform_index == index for ref in group]
        manifest['platforms'].append(platform)
        if getattr(shader, 'stageCounts', None) is not None and index < len(shader.stageCounts):
            platform['stage_count'] = shader.stageCounts[index]
        segments = {}
        try:
            offsets = _segment_row(shader.offsets, index)
            compressed = _segment_row(shader.compressedLengths, index)
            decompressed = _segment_row(shader.decompressedLengths, index)
            if not len(offsets) == len(compressed) == len(decompressed):
                raise ValueError('offsets/compressedLengths/decompressedLengths segment counts differ')
        except Exception as exc:
            diagnostic(platform, 'invalid_segment_arrays', f'{type(exc).__name__}: {exc}')
            continue
        for segment_index, (offset, clen, dlen) in enumerate(zip(offsets, compressed, decompressed)):
            segment = {'segment_index': segment_index, 'compressed_offset': offset,
                       'compressed_length': clen, 'decompressed_length': dlen}
            platform['segments'].append(segment)
            try:
                if offset < 0 or clen < 0 or dlen < 0 or offset + clen > len(blob):
                    raise ValueError('compressed segment range outside compressedBlob')
                data = CompressionHelper.decompress_lz4(blob[offset:offset + clen], dlen)
                if len(data) != dlen:
                    raise ValueError(f'decompressed length {len(data)} != declared {dlen}')
                segments[segment_index] = data
            except Exception as exc:
                diagnostic(segment, 'decompression_failed', f'{type(exc).__name__}: {exc}')
        try:
            entries = read_entries(segments[0], version)
        except Exception as exc:
            diagnostic(platform, 'entry_table_failed', f'{type(exc).__name__}: {exc}')
            continue
        for blob_index, entry in enumerate(entries):
            references = refs.get((index, blob_index), [])
            if blob_index in parameters.get(index, set()) and not references:
                platform['parameter_entries'].append({'blob_index': blob_index, **entry})
                continue
            record = {'blob_index': blob_index, **entry, 'references': references, 'status': 'failed'}
            platform['programs'].append(record)
            try:
                data = segments.get(entry['segment'])
                if data is None:
                    raise ValueError(f"data segment {entry['segment']} unavailable")
                start, length = entry['offset'], entry['length']
                if start < 0 or length < 0 or start + length > len(data):
                    raise ValueError('entry range outside decompressed segment')
                bounded = _BoundedReader(data[start:start + length])
                serialization_version = bounded.read_int()
                if serialization_version not in PROGRAM_VERSIONS:
                    raise ValueError(f'unsupported program serialization version {serialization_version}')
                bounded.Position = 0
                program = ShaderSubProgram(bounded)
                code = bytes(program.m_ProgramCode)
                record.update({'program_serialization_version': program.m_Version,
                               'gpu_program_type': enum_info(ShaderGpuProgramType, program.m_ProgramType),
                               'program_keywords': list(program.m_Keywords),
                               'code_offset_in_segment': start + bounded.payload_offset,
                               'code_length': len(code)})
                if program.m_LocalKeywords is not None:
                    record['program_local_keywords'] = list(program.m_LocalKeywords)
                for reference in references:
                    if reference['gpu_program_type']['value'] != int(program.m_ProgramType):
                        diagnostic(reference, 'gpu_type_mismatch', 'Serialized variant GPU type differs from parsed payload')
                    if version < (2021, 2):
                        reference['program_keywords'] = list(program.m_Keywords)
                        if program.m_LocalKeywords is not None:
                            reference['program_local_keywords'] = list(program.m_LocalKeywords)
                        reference['keyword_names_source'] = 'ShaderSubProgram (no serialized name table)'
                    elif 'keywords' in reference and set(reference['keywords']) != set(program.m_Keywords):
                        diagnostic(reference, 'keyword_mismatch', 'Serialized keyword names differ from stored program keyword names')
                if not code:
                    diagnostic(record, 'empty_program', 'ShaderSubProgram has an empty m_ProgramCode')
                    continue
                kind, stage, ext = _payload_type(program, references)
                record.update({'content_type': kind, 'payload_stage': stage, 'sha256': hashlib.sha256(code).hexdigest(),
                               'status': 'parsed'})
                filename = f'p{index}_{platform_value}_blob{blob_index:06d}_s{entry["segment"]}{ext}'
                payloads.append((record, filename, code))
            except Exception as exc:
                diagnostic(record, 'program_parse_failed', f'{type(exc).__name__}: {exc}')
        for (ref_platform, blob_index), references in refs.items():
            if ref_platform == index and not 0 <= blob_index < len(entries):
                diagnostic(platform, 'blob_index_out_of_range', 'Variant references a missing entry',
                           blob_index=blob_index, references=references)
    return manifest, payloads

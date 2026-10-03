# Copyright (c) 2022-2026, Harry Huang
# @ BSD 3-Clause License
import os
import os.path as osp
import importlib.util
import sys
import sysconfig
import toml


def __get_venv_dir():
    import re, subprocess

    rst = subprocess.run(["poetry", "env", "info"], capture_output=True)

    if rst.returncode == 0:
        for l in rst.stdout.splitlines():
            match = re.search(r"Path:\s+(.+)", str(l, encoding="UTF-8"))
            if match:
                path = match.group(1).strip()
                if osp.isdir(path):
                    return path
        print("× Failed to parse poetry output to query venv dir.")
    else:
        print(f"× Failed to run poetry to query venv dir. Returned code: {rst.returncode}")
        print(f"- StdErr: {rst.stderr}")
        print(f"- StdOut: {rst.stdout}")
    print("- Please check the compatibility of poetry version.")
    print("- Please check the poetry status and the venv info.")
    raise Exception("venv dir not found or poetry config failed")


def __get_proj_info():
    try:
        config = toml.load("pyproject.toml")
        config = config["project"]
        return {
            "name": config["name"],
            "version": config["version"],
            "description": config["description"],
            "author": config["authors"][0]["name"],
            "license": config["license"],
        }
    except KeyError as arg:
        print(f"x Required field missing, {arg}")
        raise arg
    except Exception as arg:
        print("× Failed to parse poetry project info.")
        raise arg


def __get_build_def(proj_dir, venv_dir):
    try:
        config = toml.load("pyproject.toml")
        build_def = {
            k: v.replace("$project$", proj_dir).replace("$venv$", venv_dir) for k, v in config["tool"]["build"].items()
        }
        # The upstream definition uses Windows' Lib/site-packages layout. Resolve
        # resources from the interpreter running this file for POSIX builds too.
        site_packages = sysconfig.get_paths()["purelib"]
        for key in ("add-binary", "add-data"):
            if key in build_def:
                build_def[key] = build_def[key].replace(
                    osp.join(venv_dir, "Lib", "site-packages"), site_packages
                )
                build_def[key] = build_def[key].replace(
                    osp.join(venv_dir, "lib", "site-packages"), site_packages
                )

        def package_dir(package_name):
            spec = importlib.util.find_spec(package_name)
            if spec is None or not spec.submodule_search_locations:
                raise ModuleNotFoundError(f"Cannot locate installed package: {package_name}")
            return next(iter(spec.submodule_search_locations))

        # Keep PyInstaller's destination paths stable while discovering the source
        # paths of platform-specific dependency resources dynamically.
        build_def["add-binary"] = "|".join(
            [
                f"{osp.join(package_dir('fmod_toolkit'), 'libfmod')}:fmod_toolkit/libfmod",
                f"{osp.join(package_dir('UnityPy'), 'resources', 'lzma.tpk')}:UnityPy/resources",
            ]
        )
        build_def["add-data"] = "|".join(
            [
                f"{osp.join(proj_dir, 'src', 'fbs', 'CN')}:src/fbs/CN",
                f"{osp.join(package_dir('archspec'), 'json')}:archspec/json",
            ]
        )
        return build_def
    except Exception as arg:
        print("× Failed to parse build definition fields.")
        raise arg


def __main():
    proj_dir = osp.dirname(osp.abspath(__file__))
    venv_dir = __get_venv_dir()
    proj_info = __get_proj_info()
    build_def = __get_build_def(proj_dir, venv_dir)
    print(f"Project: {proj_info['name']}|{proj_info['version']}|{proj_info['author']}|{proj_info['license']}")
    print(f"Root: {proj_dir}")
    print(f"Venv: {venv_dir}")
    print("")
    __build(proj_info, proj_dir, build_def)
    exit(0)


def __exec(cmd):
    rst = os.system(cmd)
    if rst == 0:
        print(f"\n[Done] <- {cmd}")
    else:
        print(f"\n[Error] <- {cmd}")
        print(f"× Execution failed! Returned code: {rst}")
        exit(1)


def __build(proj_info, proj_dir, build_def):
    import time, shutil

    t1 = time.time()

    print(f"Removing build dir...")
    os.chdir(proj_dir)
    build_dir = build_def["build-dir"]
    if osp.exists(build_dir):
        shutil.rmtree(build_dir, ignore_errors=False)

    print(f"Creating build dir...")
    os.mkdir(build_dir)
    os.chdir(build_dir)

    version_file = None
    if sys.platform == "win32":
        print(f"Creating version file...")
        version_file = "version.txt"
        with open(version_file, "w", encoding="UTF-8") as f:
            # spell-checker: disable
            f.write(
                f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
filevers=({proj_info['version'].replace('.',',')},0),
prodvers=({proj_info['version'].replace('.',',')},0),
mask=0x3f,
flags=0x0,
OS=0x4,
fileType=0x1,
subtype=0x0,
date=(0,0)
),
  kids=[
StringFileInfo([
  StringTable(
    u'040904B0',
    [StringStruct(u'CompanyName', u'{proj_info['author']}'),
    StringStruct(u'FileDescription', u'{proj_info['description']}'),
    StringStruct(u'FileVersion', u'{proj_info['version']}'),
    StringStruct(u'LegalCopyright', u'©{proj_info['author']} @{proj_info['license']} License'),
    StringStruct(u'ProductName', u'{proj_info['name']}'),
    StringStruct(u'ProductVersion', u'{proj_info['version']}')])
  ])
])
"""
            )  # End f.write
            # spell-checker: enable

    print("Running pyinstaller...")
    cmd_pyinstaller = f"poetry run pyinstaller -F"
    if sys.platform == "darwin":
        # archspec loads JSON files relative to its __file__.  PyInstaller 6's
        # one-file layout puts external data under _internal while PYZ modules
        # stay at the archive root, so keep Python modules external on macOS.
        cmd_pyinstaller += " --debug=noarchive"
    cmd_pyinstaller += f" --name \"{proj_info['name']}-v{proj_info['version']}\""
    if version_file:
        cmd_pyinstaller += f" --version-file \"{version_file}\""
    cmd_pyinstaller += f" --icon \"{build_def['icon']}\"" if "icon" in build_def.keys() else ""
    if "add-binary" in build_def.keys():
        for i in build_def["add-binary"].split("|"):
            cmd_pyinstaller += f' --add-binary "{i}"' if i else ""
    if "add-data" in build_def.keys():
        for i in build_def["add-data"].split("|"):
            cmd_pyinstaller += f' --add-data "{i}"' if i else ""
    if "hidden-import" in build_def.keys():
        for i in build_def["hidden-import"].split("|"):
            cmd_pyinstaller += f' --hidden-import "{i}"' if i else ""
    cmd_pyinstaller += f" --log-level {build_def['log-level']}" if "log-level" in build_def.keys() else ""
    cmd_pyinstaller += f" \"{build_def['entry']}\""
    __exec(cmd_pyinstaller)

    print(f"√ Build finished in {round(time.time() - t1, 1)}s!")
    print(f"- Dist files see: {osp.join(build_dir, 'dist')}")


if __name__ == "__main__":
    __main()

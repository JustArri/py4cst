#!/usr/bin/env python3

from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple
import keyword
import re
import textwrap
from dataclasses import dataclass
try:
    import tomllib # type: ignore
except:
    import tomli as tomllib # type: ignore


@dataclass
class EnumDef:
    pairs: Dict[str, str]
    dtype: str


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python tools/generate_wrappers.py <mappings_dir> <out_dir>")
        return 1

    mappings_dir = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()

    if not mappings_dir.is_dir():
        print(f"Error: {mappings_dir} is not a directory")
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    clean_old_files(out_dir)

    generate_stubs(mappings_dir, out_dir)
    # try:
    #     generate_stubs(mappings_dir, out_dir)
    # except Exception as e:
    #     print("Error:", e)
    #     return 3

    return 0


def clean_old_files(out_dir: Path):
    for f in out_dir.glob("*.py"):
        f.unlink()
    print(f"Cleaned {out_dir}")


def generate_stubs(mappings_dir: Path, out_dir: Path):
    count = 0
    sorted_paths = sorted(mappings_dir.iterdir(), key=lambda path: path.name)
    imports_modules = []
    imports_classes = []

    for mapping_file in sorted_paths:
        if not mapping_file.is_file():
            continue
        stem = mapping_file.stem  # filename without extension
        print(f"Processing {mapping_file.name}")
        gen = WrapperGen(mapping_file.read_text(encoding="utf-8"))
        code = gen.generate()
        target_file = out_dir / f"{stem}.py"
        target_file.write_text(code, encoding="utf-8")
        print(f"Wrote {target_file.name}")
        imports_modules.append(stem)
        imports_classes.append(gen.class_name)
        count += 1

    gen_init_py(Path(out_dir / "__init__.py"), imports_modules, imports_classes)
    print(f"Total {count} file(s) written into {out_dir}")


def gen_init_py(path: Path, modules: List[str], classes: List[str]):
    import_lines = "\n".join([f"from .{f} import {c}" for f,c in zip(modules, classes)])
    all_lines = "\n".join([f"    \"{c}\"," for c in classes])
    code = f"{import_lines}\n\n__all__ = [\n{all_lines}\n]\n"
    path.write_text(code, encoding="utf-8")


class WrapperGen:
    def __init__(self, content: str) -> None:
        self.content = content
        self.imports = {}
        self.enums: Dict[str, EnumDef] = {}
        self.class_name = ''
        self.obj_name = ''
        self.save_history = True
        self.add_import("..", "IVBAProvider")
        self.add_import("..", "VBAObjWrapper")

    def generate(self) -> str:
        data = check_toml(self.content)
        self.obj_name = get_param_object(data)
        self.class_name = get_param_class_name(data)
        if self.class_name is None:
            self.class_name = check_identifier("object", self.obj_name)
        self.save_history = get_param_save_history(data)

        p_imports = get_param_imports(data)
        for imp in p_imports:
            self.add_import(imp[0], imp[1], imp[2])

        p_enums = get_param_enums(data)
        if p_enums is not None:
            self.add_import("enum", "Enum")
            self._process_enums(p_enums)

        save_history_str = "\n        self.set_save_history(False)" if not self.save_history else ""

        methods = get_param_methods(data)
        methods_str = "" if methods is None else self._gen_methods(methods)

        return (
            "'''This file is auto-generated. Do not edit.'''\n"
            f"{self._gen_import_lines()}"
            f"class {self.class_name}(VBAObjWrapper):\n"
            f"{generate_enums(self.enums)}"
            f"    def __init__(self, vbap: IVBAProvider) -> None:\n"
            f"        super().__init__(vbap, '{self.obj_name}'){save_history_str}\n\n"
            f"{methods_str}"
        )

    def add_import(self, module: str, attrib: Optional[str] = None, alias: Optional[str] = None):
        if module not in self.imports:
            self.imports[module] = set()
        self.imports[module].add((attrib, alias))

    def _gen_import_lines(self) -> str:
        lines = []
        for module,sub in self.imports.items():
            sub = list(sub)
            self_indices = [i for i,s in enumerate(sub) if s[0] is None]
            for idx in self_indices:
                s = sub[idx]
                alias_code = "" if s[1] is None else f" as {s[1]}"
                lines.append(f"import {module}{alias_code}")
            sub = [s for i,s in enumerate(sub) if i not in self_indices]
            if len(sub) > 0:
                def map_sub(x):
                    if x[1] is not None:
                        return f"{x[0]} as {x[1]}"
                    return x[0]
                sub_code = ", ".join([map_sub(s) for s in sub])
                lines.append(f"from {module} import {sub_code}")
        if len(lines) == 0:
            return ""
        lines_joined = "\n".join(lines)
        return f"{lines_joined}\n\n"

    def _process_enums(self, enums: List[Any]) -> None:
        for i, enum in enumerate(enums):
            id = f"enums[{i}]"
            enum = check_dict(id, enum)
            name, enum_def = process_enum(id, enum)
            if name in self.enums:
                raise ValueError(f"duplicate enum: {name}")
            self.enums[name] = enum_def

    def _gen_methods(self, methods: List[Any]) -> str:
        lines = []
        for i, method in enumerate(methods):
            id = f"methods[{i}]"
            method = check_dict(id, method)
            lines.append(self._gen_method(id, method))
        return "\n\n".join(lines) + "\n\n"

    def _gen_method(self, id: str, method: Mapping[str, Any]) -> str:
        name = require_field(f"{id}.name", method, "name")
        name = check_string(f"{id}.name", name)
        orig_id = id
        id = f'{orig_id}:"{name}"'

        py_name = method.get("py_name")
        if py_name is None:
            py_name = vba_name_to_python(name)
        else:
            py_name = check_identifier(f"{id}.py_name", py_name)
        id = f'{orig_id}:"{name}"/"{py_name}"'

        method_id = id

        override_class = method.get("override_class")
        if override_class is not None:
            override_class = check_str_identifier(f"{id}.override_class", override_class)

        known_dtypes = ["bool", "int", "float", "complex", "str"]
        valid_ret_dtypes = ["bool", "int", "float", "str"]
        valid_vba_types = [
            "Byte",
            "Integer",
            "Long",
            "String",
            "Single",
            "Double",
            "Boolean",
            "Variant",
        ]

        ret_dtype = method.get("return_type")
        ret_dtype_is_enum = False
        ret_tuple_dtypes = None
        ret_tuple_dtypes_is_enum = {}
        ret_tuple_retval_dtype = "None"
        ret_tuple_retval_dtype_is_enum = False
        py_ret_dtype = method.get("python_return_type")
        py_ret_dtype_is_enum = False

        if ret_dtype is None:
            ret_dtype = "None"
        elif isinstance(ret_dtype, str):
            if ret_dtype in self.enums.keys():
                ret_dtype_is_enum = True
            elif ret_dtype not in valid_ret_dtypes:
                raise ValueError(f"invalid return type: [{id}]: {ret_dtype}")
        elif isinstance(ret_dtype, dict):
            self.add_import("typing", "Tuple")
            ret_tuple_dtypes = ret_dtype
            ret_dtype = "Tuple"
            if "__retval__" in ret_tuple_dtypes:
                ret_tuple_retval_dtype = ret_tuple_dtypes["__retval__"]
                if ret_tuple_retval_dtype in self.enums.keys():
                    ret_tuple_retval_dtype_is_enum = True
                elif ret_tuple_retval_dtype not in valid_vba_types:
                    raise ValueError(
                        f"invalid return type: [{id}]: {ret_tuple_retval_dtype}, must be VBA type {valid_vba_types} or enum"
                    )
                del ret_tuple_dtypes["__retval__"]
            for param_name, param_t in ret_tuple_dtypes.items():
                ret_tuple_dtypes_is_enum[param_name] = False
                if param_t in self.enums.keys():
                    ret_tuple_dtypes_is_enum[param_name] = True
                elif param_t not in valid_vba_types:
                    raise ValueError(
                        f"invalid param type: [{id}[{param_name}]]: {param_t}, must be VBA type {valid_vba_types} or enum"
                    )
        else:
            raise ValueError(f"invalid return type: [{id}]: {ret_dtype}")

        if py_ret_dtype is None:
            py_ret_dtype = "None"
        elif isinstance(py_ret_dtype, str):
            if py_ret_dtype in self.enums.keys():
                py_ret_dtype_is_enum = True
            #TODO: validate python return type?
        else:
            raise ValueError(f"invalid Python return type: [{id}]: {py_ret_dtype}")

        ret_mapping = method.get("map_return_value")
        if ret_mapping is not None:
            if ret_dtype == "None":
                raise ValueError(f"unsupported field: [{id}.map_return_value]: method has no return value")
            ret_mapping = check_string(f"{id}.map_return_value", ret_mapping)
            ret_mapping = check_non_empty(f"{id}.map_return_value", ret_mapping)
        elif py_ret_dtype != "None" and ret_dtype != py_ret_dtype:
            raise ValueError(f"missing required field: [{id}.map_return_value]")

        return_val_desc = method.get("return_value_description")
        if ret_mapping is not None and return_val_desc is None:
            raise ValueError(f"missing required field: [{id}.return_value_description]")
        if return_val_desc is not None:
            return_val_desc = check_string(f"{id}.return_value_description", return_val_desc)

        record_history = check_bool(f"{id}.record_history", method.get("record_history", True))
        if not record_history and (method.get("cache", False) or method.get("flush_cache") is not None):
            raise ValueError(f"incompatible parameters: [{id}]: direct methods cannot cache or flush")

        cache = method.get("cache", False)
        cache = check_bool(f"{id}.cache", cache)
        if cache and ret_dtype != "None":
            raise ValueError(
                f"incompatible parameters: [{id}]: cached methods cannot return values"
            )

        flush_cache = method.get("flush_cache")
        if flush_cache is not None:
            if not cache:
                raise ValueError(
                    f"incompatible parameters: [{id}]: non-cached methods cannot flush cache"
                )
            if ret_dtype != "None":
                raise ValueError(
                    f"incompatible parameters: [{id}]: methods cannot flush cache and return values"
                )
            flush_cache = check_string(f"{id}.flush_cache", flush_cache)
            flush_cache = check_non_empty(f"{id}.flush_cache", flush_cache)

        py_args = ["self"]

        vba_call_args = method.get("vba_call_args")
        if vba_call_args is not None:
            if ret_dtype == "Tuple":
                raise RuntimeError(
                    f"vba_call_args not supported for tuple return type: [{id}]"
                )

            vba_call_args = check_list(f"{id}.vba_call_args", vba_call_args)
            vba_call_args_docs = [str(x) for x in vba_call_args]

        args = method.get("args")
        arg_map = {}
        arg_list = []
        arg_maps = {}
        arg_expansions = {}
        arg_optionals = {}
        enum_args = []
        if args is not None:
            args = check_list(f"{id}.args", args)

            for i, arg in enumerate(args):
                arg = check_dict(f"{id}.args[{i}]", arg)
                arg_name = require_field(f"{id}.args[{i}].name", arg, "name")
                arg_name = check_string(f"{id}.args[{i}].name", arg.get("name"))
                dtype = require_field(f"{id}.args[{i}].type", arg, "type")
                dtype = check_string(f"{id}.args[{i}].type", dtype)
                dtype = check_non_empty(f"{id}.args[{i}].type", dtype)
                dimension = arg.get("dimension", 1)
                if dimension is not None:
                    dimension = check_positive_int(f"{id}.args[{i}].dimension", dimension)
                expansion_method = arg.get("expansion_method")
                if expansion_method is not None:
                    expansion_method = check_string(f"{id}.args[{i}].expansion_method", expansion_method)
                    arg_expansions[arg_name] = expansion_method
                optional = arg.get("optional", False)
                optional = check_bool(f"{id}.args[{i}].optional", optional)
                arg_optionals[arg_name] = optional

                if dtype == "__retval__":
                    if ret_tuple_dtypes is None or arg_name not in ret_tuple_dtypes:
                        raise ValueError(
                            f'invalid return argument: [{id}.args[{i}]:"{arg_name}"]'
                        )
                    arg_ret_type = ret_tuple_dtypes[arg_name]
                    enum_mapping = arg.get("map_enum")
                    if enum_mapping:
                        enum_name = require_field(
                            f"{id}.args[{i}].map_enum.name", enum_mapping, "name"
                        )
                        if enum_name not in self.enums:
                            raise ValueError(
                                f'undefined enum: [{id}.args[{i}]]:"{arg_name}"]: {enum_name}'
                            )
                        enum_values = require_field(
                            f"{id}.args[{i}].map_enum.values", enum_mapping, "values"
                        )
                        enum_values = check_anykey_dict(
                            f"{id}.args[{i}].map_enum.values", enum_values
                        )
                        enum_def = self.enums[enum_name]
                        arg_map = {}
                        for ek, ev in enum_values.items():
                            if arg_ret_type in ["Byte", "Integer", "Long"]:
                                ek = int(ek)
                            elif arg_ret_type in ["Single", "Double"]:
                                ek = float(ek)
                            elif arg_ret_type == "Boolean":
                                ek = ek != "False"
                            enum_key = next(
                                (k for k, v in enum_def.pairs.items() if v == ev), None
                            )
                            if enum_key is None:
                                raise ValueError(
                                    f'invalid enum value: [{id}.args[{i}]]:"{arg_name}"]: {ev}'
                                )
                            arg_map[ek] = f"{self.class_name}.{enum_name}.{enum_key}"
                        arg_maps[arg_name] = arg_map
                    arg_list.append(arg_name)

                else:
                    arg_map[arg_name] = (dtype, dimension)
                    arg_list.append(arg_name)

                    if dtype in self.enums:
                        enum_args.append(arg_name)
                        self.add_import("typing", "Union")
                        enum_dtype = self.enums[dtype].dtype
                        dtype = f"Union[{dtype}, {enum_dtype}]"
                    elif dtype not in known_dtypes and vba_call_args is None:
                        raise ValueError(
                            f"unknown data type: [{id}.args[{i}].type]: {dtype}, VBA call args must be provided"
                        )

                    if dimension == 1:
                        type_str = dtype
                    else:
                        self.add_import("typing", "Tuple")
                        targs = ", ".join([dtype] * dimension)
                        type_str = f"Tuple[{targs}]"

                    if optional:
                        self.add_import("typing", "Optional")
                        type_str = f"Optional[{type_str}]"

                    default = arg.get("default")
                    if default is None:
                        def_val_str = ""
                    elif isinstance(default, str):
                        def_val_str = f" = '{default}'"
                    elif isinstance(default, dict) and len(default.keys()) == 0:
                        def_val_str = " = None"
                    else:
                        def_val_str = f" = {default}"

                    py_args.append(f"{arg_name}: {type_str}{def_val_str}")

        if vba_call_args is None:
            vba_call_args = []
            vba_call_args_docs = []
            if ret_dtype == "Tuple":
                if ret_tuple_retval_dtype != "None":
                    self.add_import("..", "VBATypeName")
                    vba_retval_dtype = "String" if ret_tuple_retval_dtype_is_enum else ret_tuple_retval_dtype
                    vba_call_args.append(f"VBATypeName.{vba_retval_dtype}")
                else:
                    vba_call_args.append("None")
            for arg_name in arg_list:
                if arg_name in arg_map:
                    type_name = arg_map[arg_name][0]
                    count = arg_map[arg_name][1]
                    for i in range(count):
                        id = arg_name if count == 1 else f"{arg_name}[{i}]"
                        if type_name == "complex":
                            expansion = 'real/imag' if arg_name not in arg_expansions else arg_expansions[arg_name]
                            if expansion == 'real/imag':
                                vba_call_args.append(f"{id}.real")
                                vba_call_args.append(f"{id}.imag")
                                vba_call_args_docs.append(f"real({id})")
                                vba_call_args_docs.append(f"imag({id})")
                            elif expansion == 'imag/real':
                                vba_call_args.append(f"{id}.imag")
                                vba_call_args.append(f"{id}.real")
                                vba_call_args_docs.append(f"imag({id})")
                                vba_call_args_docs.append(f"real({id})")
                            elif expansion == 'abs/phase':
                                self.add_import("cmath")
                                vba_call_args.append(f"abs({id})")
                                vba_call_args.append(f"cmath.phase({id})")
                                vba_call_args_docs.append(f"abs({id})")
                                vba_call_args_docs.append(f"angle({id})")
                            elif expansion == 'phase/abs':
                                self.add_import("cmath")
                                vba_call_args.append(f"cmath.phase({id})")
                                vba_call_args.append(f"abs({id})")
                                vba_call_args_docs.append(f"angle({id})")
                                vba_call_args_docs.append(f"abs({id})")
                            else:
                                raise ValueError(f"invalid expansion method '{expansion}' @ {method_id}.{id}, possible values: ['real/imag', 'imag/real', 'abs/phase', 'phase/abs']")
                        elif type_name in self.enums:
                            enum_dtype = self.enums[type_name].dtype
                            vba_call_args.append(f"{enum_dtype}(getattr({id}, 'value', {id}))")
                            vba_call_args_docs.append(str(id))
                        else:
                            expanded = False
                            if type_name in ["int", "float"] and arg_optionals[arg_name] and arg_name in arg_expansions:
                                if arg_expansions[arg_name] == 'flag/value':
                                    expanded = True
                                    def_val = "0" if type_name == "int" else "0.0"
                                    arg0 = f"{id} is None"
                                    arg1 = f"{id} or {def_val}"
                                    vba_call_args.append(arg0)
                                    vba_call_args.append(arg1)
                                    vba_call_args_docs.append(arg0)
                                    vba_call_args_docs.append(arg1)
                                else:
                                    raise ValueError(f"invalid expansion method '{expansion}' @ {method_id}.{id}, possible values: ['flag/value']")

                            if not expanded:
                                vba_call_args.append(id)
                                vba_call_args_docs.append(str(id))
                else:
                    assert isinstance(ret_tuple_dtypes, dict)
                    self.add_import("..", "VBATypeName")
                    vba_type_name = "String" if ret_tuple_dtypes_is_enum[arg_name] else ret_tuple_dtypes[arg_name]
                    vba_call_args.append(f"VBATypeName.{vba_type_name}")
                    vba_call_args_docs.append(f"&{arg_name}")

        vba_call_args = [f"'{name}'", *map(lambda x: str(x), vba_call_args)]

        vba_call_args_code = ", ".join(vba_call_args)
        vba_call_args_docs = ", ".join(vba_call_args_docs)
        py_args_code = ", ".join(py_args)
        if py_ret_dtype_is_enum:
            py_ret_dtype_code = "str"
        elif py_ret_dtype == "None":
            py_ret_dtype_code = ret_dtype
        else:
            py_ret_dtype_code = py_ret_dtype
        def_line = f"def {py_name}({py_args_code}) -> {py_ret_dtype_code}:"

        body_lines = []
        vba_class_name = self.obj_name if override_class is None else override_class
        docs_lines = ["VBA Call", "--------", f"{vba_class_name}.{name}({vba_call_args_docs})"]

        method_desc = method.get("description")
        if method_desc is not None:
            method_desc = check_string(f"{id}.description", method_desc)
            docs_lines.extend(["", "Description", "--------", method_desc])

        self_expr = "self"
        if override_class is not None:
            self_expr = f"{override_class}(self.vbap)"

        if ret_dtype == "Tuple":
            assert isinstance(ret_tuple_dtypes, dict)
            ret_names = []
            if ret_tuple_retval_dtype != "None":
                ret_names.append("VBA return value")
            ret_names.extend(ret_tuple_dtypes.keys())
            ret_names = ", ".join(ret_names)
            docs_lines.extend(["", "Returns", "-------"])
            if ret_mapping is None:
                docs_lines.append(f"({ret_names})")
            else:
                docs_lines.append(return_val_desc)

            if len(arg_maps) > 0 or ret_tuple_retval_dtype_is_enum or any(ret_tuple_dtypes_is_enum.values()):
                body_lines.append(
                    indent(f"__retval__ = list({self_expr}.query_method_t({vba_call_args_code}))")
                )
                if ret_tuple_retval_dtype_is_enum:
                    body_lines.append(
                        indent(f"__retval__[0] = {self.class_name}.{ret_tuple_retval_dtype}(__retval__[0])")
                    )
                ret_tuple_dtypes_keys = list(ret_tuple_dtypes.keys())
                offset = 0 if ret_tuple_retval_dtype == "None" else 1
                for arg_name, arg_map in arg_maps.items():
                    index = ret_tuple_dtypes_keys.index(arg_name) + offset
                    body_lines.append(
                        indent(f"{arg_name}_map = {argmap_to_code_str(arg_map)}")
                    )
                    body_lines.append(
                        indent(f"__retval__[{index}] = {arg_name}_map.get(__retval__[{index}])")
                    )
                for arg_name,is_enum in ret_tuple_dtypes_is_enum.items():
                    if is_enum:
                        index = ret_tuple_dtypes_keys.index(arg_name) + offset
                        body_lines.append(
                            indent(f"__retval__[{index}] = {self.class_name}.{ret_tuple_dtypes[arg_name]}(__retval__[{index}])")
                        )
                if ret_mapping is not None:
                    body_lines.append(indent(f"return {ret_mapping}"))
                else:
                    body_lines.append(indent("return tuple(__retval__)"))
            else:
                if ret_mapping is not None:
                    body_lines.append(
                        indent(f"__retval__ = {self_expr}.query_method_t({vba_call_args_code})")
                    )
                    body_lines.append(indent(f"return {ret_mapping}"))
                else:
                    body_lines.append(
                        indent(f"return {self_expr}.query_method_t({vba_call_args_code})")
                    )

        else:
            if ret_dtype != "None":
                method_dtype = "str" if ret_dtype_is_enum else ret_dtype
                hl_method = f"query_method_{method_dtype}"
            else:
                hl_method = "cache_method" if cache else ("record_method" if record_history else "invoke_method")

            if ret_mapping is not None:
                body_lines.append(indent(f"__retval__ = {self_expr}.{hl_method}({vba_call_args_code})"))
                body_lines.append(indent(f"return {ret_mapping}"))
            elif ret_dtype_is_enum:
                body_lines.append(indent(f"__retval__ = {self_expr}.{hl_method}({vba_call_args_code})"))
                body_lines.append(indent(f"return {self.class_name}.{ret_dtype}(__retval__)"))
            else:
                ret_code = "return " if ret_dtype != "None" else ""
                body_lines.append(
                    indent(f"{ret_code}{self_expr}.{hl_method}({vba_call_args_code})")
                )

            if flush_cache is not None:
                body_lines.append(indent(f"{self_expr}.flush_cache('{flush_cache}')"))

        if len(docs_lines) > 0:
            docs_lines = ['"""', *docs_lines, '"""']

        lines = [def_line, indent("\n".join(docs_lines)), *body_lines]

        return indent("\n".join(lines))


def process_enum(id: str, enum: Dict[str, Any]) -> Tuple[str, EnumDef]:
    name = require_field(f"{id}.name", enum, "name")
    name = check_string(f"{id}.name", name)
    name = check_identifier(f"{id}.name", name)
    values = require_field(f"{id}.values", enum, "values")
    values = check_list(f"{id}.values", values)
    py_names = []
    py_values = []
    dtype = None
    for i, value in enumerate(values):
        if isinstance(value, (str, int)):
            if dtype is None:
                dtype = type(value).__name__
            if type(value).__name__ != dtype:
                raise ValueError(f"invalid [{id}]: mixed value data types")
            py_names.append(to_enum_name(value))
            py_values.append(value)
        elif isinstance(value, dict):
            vname = value.get("name")
            vname = check_str_identifier(f"{id}.values[{i}].name", vname)
            vvalue = value.get("value")
            if not isinstance(vvalue, (str, int)):
                raise ValueError(f"invalid [{id}.values[{i}].value]: must be int or string")
            if dtype is None:
                dtype = type(vvalue).__name__
            if type(vvalue).__name__ != dtype:
                raise ValueError(f"invalid [{id}]: mixed value data types")
            py_names.append(vname.upper())
            py_values.append(vvalue)
        else:
            raise ValueError(f"invalid [{id}.values[{i}]]: must be int, string or dict")
    return name, EnumDef(pairs=dict(zip(py_names, py_values)), dtype=dtype)


def generate_enums(enums: Dict[str, EnumDef]) -> str:
    lines = []
    for name, enum_def in enums.items():
        enum_lines = generate_enum(name, enum_def)
        lines.append(indent(enum_lines))
    return "\n\n".join(lines) + "\n\n"


def generate_enum(enum_name: str, enum_def: EnumDef) -> str:
    if enum_def.dtype == 'str':
        lines = "\n".join([f"{n} = '{v}'" for n, v in enum_def.pairs.items()])
    else:
        lines = "\n".join([f"{n} = {v}" for n, v in enum_def.pairs.items()])
    return f"class {enum_name}(Enum):\n{indent(lines)}"


def argmap_to_code_str(d: Dict[Any, str]) -> str:
    parts = []
    for k, v in d.items():
        if isinstance(k, str):
            key_str = f"'{k}'"
        else:
            key_str = str(k)
        value_str = str(v)
        parts.append(f"{key_str}: {value_str}")
    return "{" + ", ".join(parts) + "}"


def val_to_code(val: Any):
    if isinstance(val, str):
        return f"'{val}'"
    else:
        return str(val)


def vba_name_to_python(s: str) -> str:
    s = str(s)

    # Normalize non-word separators to underscores (space, dot, hyphen, etc.)
    s = re.sub(r"[^\w]+", "_", s)

    # Split acronym-to-Camel boundary: 'HTMLParser' -> 'HTML_Parser'
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)

    # Split lower/digit-to-Upper: 'tryParse2D' -> 'try_Parse2D'
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)

    # Lowercase and collapse multiple underscores
    s = re.sub(r"_+", "_", s).strip("_").lower()

    # Ensure valid Python identifier
    if s and s[0].isdigit():
        s = "_" + s
    if keyword.iskeyword(s):
        s += "_"

    return s or "_"


def to_enum_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be a string")

    s = value.strip()
    if not s:
        raise ValueError("value must be non-empty")

    # Insert underscores at case/number boundaries:
    # 1) Acronym + Word: 'HTMLParser' -> 'HTML_Parser'
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    # 2) Lowercase/digit + Uppercase: 'tryParse2D' -> 'try_Parse2D'
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    # 3) Letter + Digit or Digit + Letter: 'RGB24ToHex' -> 'RGB24_To_Hex', 'ver2alpha' -> 'ver2_alpha'
    s = re.sub(r"([A-Za-z])(\d)", r"\1_\2", s)
    s = re.sub(r"(\d)([A-Za-z])", r"\1_\2", s)

    # Normalize all non-alphanumeric runs (spaces, hyphens, dots, etc.) to underscores
    s = re.sub(r"[^A-Za-z0-9]+", "_", s)

    # Collapse repeats, trim edges, upper-case
    s = re.sub(r"_+", "_", s).strip("_").upper()

    if not s:
        raise ValueError("value has no alphanumeric characters")

    # Make a valid Python identifier if desired
    if s[0].isdigit():
        s = "_" + s
    if keyword.iskeyword(s):
        s += "_"

    return s


def get_param_object(data: Mapping[str, Any]) -> str:
    name = "object"
    value = require_field(name, data, name)
    value = check_string(name, value)
    value = check_non_empty(name, value)
    return value


def get_param_class_name(data: Mapping[str, Any]) -> Optional[str]:
    name = "class_name"
    value = data.get(name)
    if value is None:
        return None
    value = check_string(name, value)
    value = check_identifier(name, value)
    return value


def get_param_save_history(data: Mapping[str, Any]) -> bool:
    # Match VBAObjWrapper's default; only an explicit false opts out.
    return check_bool("save_history", data.get("save_history", True))


def get_param_imports(data: Mapping[str, Any]) -> Optional[str]:
    name = "imports"
    imports = []
    value = data.get(name)
    if value is None:
        return imports
    value = check_list(name, value)
    for i,entry in enumerate(value):
        entry = check_dict(f"{name}[{i}]", entry)
        module = require_field(f"{name}[{i}].module", entry, "module")
        module = check_import_module(f"{name}[{i}].module", module)
        attrib = entry.get("attribute")
        if attrib is not None:
            attrib = check_identifier(f"{name}[{i}].attribute", attrib)
        alias = entry.get("alias")
        if alias is not None:
            alias = check_identifier(f"{name}[{i}].alias", alias)
        imports.append((module, attrib, alias))
    return imports


def get_param_enums(data: Mapping[str, Any]) -> Optional[List[Any]]:
    name = "enums"
    value = data.get(name)
    if value is None:
        return None
    value = check_list(name, value)
    return value


def get_param_methods(data: Mapping[str, Any]) -> Optional[List[Any]]:
    name = "methods"
    value = data.get(name)
    if value is None:
        return None
    value = check_list(name, value)
    return value


def indent(x: str) -> str:
    def should_indent(line):
        return line.strip() != ""
    return textwrap.indent(x, "    ", predicate=should_indent)


def check_toml(content: str) -> dict[str, Any]:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"invalid format: {e}") from e
    return data or {}


def require_field(name: str, collection: Mapping[str, Any], key: str) -> Any:
    value = collection.get(key)
    if value is None:
        raise TypeError(f"missing required field [{name}]")
    return value


def check_bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"invalid [{name}]: must be string")
    return value


def check_positive_int(name: str, value: Any) -> bool:
    if not isinstance(value, int) or value < 1:
        raise TypeError(f"invalid [{name}]: must be positive integer")
    return value


def check_string(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"invalid [{name}]: must be string")
    return value.strip()


def check_non_empty(name: str, value: str) -> str:
    if not value:
        raise ValueError(f"invalid [{name}]: must be non-empty")
    return value


def check_identifier(name: str, value: str) -> str:
    check_non_empty(name, value)
    if not value.isidentifier() or keyword.iskeyword(value):
        raise ValueError(f"invalid [{name}]: must be valid Python identifier")
    return value


def check_import_module(name: str, value: str) -> str:
    check_non_empty(name, value)
    cvalue = value
    if value.startswith('..'):
        cvalue = value[2:]
    elif value.startswith('.'):
        cvalue = value[1:]
    if not cvalue.isidentifier() or keyword.iskeyword(cvalue):
        raise ValueError(f"invalid [{name}]: must be valid Python module")
    return value


def check_str_identifier(name: str, value: Any) -> str:
    value = check_string(name, value)
    value = check_non_empty(name, value)
    if not value.isidentifier() or keyword.iskeyword(value):
        raise ValueError(f"invalid [{name}]: must be valid Python identifier")
    return value


def check_list(name: str, value: Any) -> List[Any]:
    if not isinstance(value, list):
        raise TypeError(f"invalid [{name}]: must be list")
    return value


def check_all_non_empty_strings(name: str, values: List[Any]) -> List[str]:
    for i, value in enumerate(values):
        value = check_string(f"{name}[{i}]", value)
        check_non_empty(f"{name}[{i}]", value)
    return values


def check_dict(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"invalid [{name}]: must be dict")
    return value


def check_anykey_dict(name: str, value: Any) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"invalid [{name}]: must be dict")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

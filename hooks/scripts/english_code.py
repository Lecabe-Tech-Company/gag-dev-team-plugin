"""Check changed code identifiers against a pinned English word list."""
import ast
from collections import Counter
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DICTIONARY = ROOT / "language_data" / "en_US.txt"
DICTIONARY_SHA256 = "4ff7e0b6d86763e1e042ffd746e94cdf4432618702deac303a1669e2a838db04"
SUPPORTED_EXTENSIONS = {".py", ".php", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".json", ".toml", ".css", ".sh", ".bash", ".yaml", ".yml"}
NON_ENGLISH_HOMOGRAPHS = {"nome", "dados", "valor", "valores"}
TECHNICAL_WORDS = {
    # npm package-lock schema contract.
    "lockfile",
    # Exact Python standard-library and process/platform API names.
    "urllib", "urlsafe", "pid", "creationflags", "popen", "getsockname", "timedelta",
    "fdopen", "fileno", "infolist", "wronly", "attr", "sha",
    # Exact npm/TypeScript, DOM/HTML, CSS UI, and JavaScript API vocabulary.
    "dev", "tsconfig", "js", "ts", "interop", "jsx", "globals", "nav", "topbar",
    "params", "pathname", "href", "h1", "h2", "thead", "tbody", "intl", "auth",
    "loopback", "stringify", "concat",
    "gh", "xdg",
    # JSON Schema keywords and exact Python mapping/date/filesystem/HTTP APIs.
    "const", "enum", "defs", "setdefault", "fromisoformat", "tzinfo", "mkstemp",
    "fchmod", "astimezone", "strftime", "isalnum", "wfile",
    "lifecycle", "sigterm", "executables",
    # Python standard-library contracts and the exact external npm package name.
    "getpid", "base64", "b64encode", "sha512", "lightningcss",
    # Exact SVG/HTML and agent-kind contract vocabulary.
    "svg", "svgsvg", "linecap", "linejoin", "focusable", "magicpen", "h3", "orchestrator", "subagent",
    "describedby",  # Standard aria-describedby accessibility attribute.
    # Exact Windows environment keys, Python stat field, and backend link state.
    "userprofile", "localappdata", "ino", "unlinked",
    # Standard-library, operating-system, Git, and skill-format contracts.
    "argparse", "dest", "dirname", "isatty", "prog", "subparsers",
    "abspath", "bool", "contextmanager", "copyfile", "copytree", "creat", "datetime", "dirs",
    "env", "environ", "expanduser", "extractfile", "fcntl", "frontmatter", "fstat", "fsync",
    "fullmatch", "getmembers", "imode", "isfile", "isoformat", "issubset", "iterdir", "joinpath",
    "lk", "lseek", "msvcrt", "namelist", "namespace", "nblck", "npm", "oversized", "pathsep",
    "posix", "pythoncoerceclocale", "pythonpath", "pythonutf8", "rdwr", "rglob", "rmdir", "rmtree",
    "roundtrip", "roundtrips", "rstrip", "scripta", "symlink", "symlinked", "tarfile", "unlck",
    "unmanifested", "utf8", "uuid4", "versionable", "worktree", "worktrees",
    # Exact Python standard-library contracts and established development terms.
    "casefold", "chmod", "contextlib", "devnull", "extensionless", "extractall", "frontend",
    "getvalue", "mkdir", "stderr", "tempfile", "unittest", "unlink", "util", "zipfile",
    "api", "args", "ascii", "aws", "ci", "cli", "cls", "css", "csrf", "db", "dns", "html",
    "http", "https", "id", "ide", "ios", "ip", "json", "jwt", "kwargs", "mcp", "mvc",
    "oauth", "php", "pr", "qa", "sdd", "self", "sku", "sql", "ssh", "tcp", "tls", "ui",
    "input", "uri", "url", "uuid", "utf", "ux", "xml", "yaml", "yml",
    "asname", "ast", "attribute", "builtins", "case", "child", "children", "cls", "comprehension",
    "context", "decode", "decoder", "dict", "encoded", "encoding", "enumerate", "except", "exec",
    "exception", "false", "filter", "float", "frozenset", "function", "getattr", "hasattr", "hash",
    "importlib", "init", "int", "isinstance", "iter", "iterator", "kwargs", "len", "list", "lineno",
    "mapping", "match", "module", "nonlocal", "none", "object", "ord", "parse", "parser", "pathlib",
    "phpunit", "pest", "python", "read_bytes", "read_text", "repr", "runtime", "set", "setattr",
    "slice", "sorted", "stdin", "stdout", "str", "subprocess", "suite", "sys", "testcase", "tokenize",
    "tomllib", "true", "tuple", "tree", "tree_sitter", "type", "unicode", "valueerror", "version",
    "yield", "zip",
    "carbon", "config", "cwd", "eloquent", "endswith", "filament", "findall", "finditer", "fromkeys",
    "fsdecode", "graphify", "hashlib", "hexdigest", "isalpha", "isascii", "livewire",
    "isspace", "laravel", "lstrip", "multiline", "readline", "returncode", "sha256", "shutil",
    "splitlines", "startswith", "spatie", "toml", "tsx", "argv",
}
TOKEN_PATTERN = re.compile(r"[^\W\d]\w*", re.UNICODE)
IDENTIFIER_SPLIT_PATTERN = re.compile(r"[^A-Za-z]+")
JSON_KEY_PATTERN = re.compile(r'"((?:\\.|[^"\\])*)"\s*:')
TREE_SITTER_LANGUAGES = {
    ".sh": ("tree_sitter_bash", "bash"),
    ".bash": ("tree_sitter_bash", "bash"),
    ".css": ("tree_sitter_css", "css"),
    ".php": ("tree_sitter_php", "php"),
    ".js": ("tree_sitter_javascript", "javascript"),
    ".jsx": ("tree_sitter_javascript", "javascript"),
    ".mjs": ("tree_sitter_javascript", "javascript"),
    ".cjs": ("tree_sitter_javascript", "javascript"),
    ".ts": ("tree_sitter_typescript", "typescript"),
    ".tsx": ("tree_sitter_typescript", "tsx"),
}
_DICTIONARY_CACHE = {}


class LanguageCheckError(RuntimeError):
    """Raised when changed code cannot be analyzed with the bundled resources."""


def load_dictionary():
    try:
        contents = DICTIONARY.read_bytes()
        text = contents.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise LanguageCheckError("The bundled English identifier dictionary is unavailable.") from error
    if hashlib.sha256(contents).hexdigest() != DICTIONARY_SHA256:
        raise LanguageCheckError("The bundled English identifier dictionary failed its integrity check.")
    if DICTIONARY_SHA256 in _DICTIONARY_CACHE:
        return _DICTIONARY_CACHE[DICTIONARY_SHA256]
    lines = text.splitlines()
    if len(lines) != 109902:
        raise LanguageCheckError("The bundled English identifier dictionary is incomplete.")
    words = set()
    for line in lines:
        word = line.strip().lower()
        if word and word.isascii() and word.isalpha():
            words.add(word)
    if len(words) < 30000:
        raise LanguageCheckError("The bundled English identifier dictionary is invalid.")
    dictionary = words | TECHNICAL_WORDS
    _DICTIONARY_CACHE[DICTIONARY_SHA256] = dictionary
    return dictionary


def split_identifier(value):
    separated = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    separated = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", separated)
    return [piece.lower() for piece in IDENTIFIER_SPLIT_PATTERN.split(separated) if piece]


def is_english_word(word, dictionary):
    if word in NON_ENGLISH_HOMOGRAPHS:
        return False
    return word in dictionary


def _tokens_for_name(value):
    if not isinstance(value, str):
        return []
    separated = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    separated = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", separated)
    separated = separated.replace("_", " ")
    return [token.lower() for token in TOKEN_PATTERN.findall(separated)]


def _tree_sitter_interpreter(graphify_binary):
    candidates = []
    executable = (shutil.which(graphify_binary) if graphify_binary else None) or shutil.which("graphify")
    if not executable:
        local_graphify = Path.home() / ".local" / "bin" / "graphify"
        if local_graphify.is_file():
            executable = str(local_graphify)
    if executable:
        binary = Path(executable)
        try:
            with binary.open(encoding="utf-8") as stream:
                first_line = stream.readline().strip()
        except (OSError, UnicodeError):
            first_line = ""
        if first_line.startswith("#!"):
            candidates.append(first_line[2:].split()[0])
        candidates.extend(str(binary.parent / name) for name in ("python", "python3", "python.exe"))
        if binary.parent.name.lower() == "scripts":
            candidates.append(str(binary.parent / "python.exe"))
    candidates.extend((sys.executable,))
    for candidate in dict.fromkeys(candidates):
        if not candidate or not Path(candidate).is_file():
            continue
        check = subprocess.run(
            [candidate, "-I", "-c", "import tree_sitter, tree_sitter_php, tree_sitter_javascript, tree_sitter_typescript"],
            capture_output=True, timeout=10,
        )
        if check.returncode == 0:
            return candidate
    raise LanguageCheckError("Tree-sitter grammars for the changed language are unavailable; install Graphify and retry.")


def _parse_tree_sitter_files(files, graphify_binary):
    if not files:
        return {}
    interpreter = _tree_sitter_interpreter(graphify_binary)
    request = [{"path": path, "content": content} for path, content in files.items()]
    try:
        result = subprocess.run(
            [interpreter, "-I", str(Path(__file__).resolve()), "parse-tree-sitter"],
            input=json.dumps(request), text=True, capture_output=True, timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LanguageCheckError("Tree-sitter could not analyze the changed source files.") from error
    if result.returncode != 0:
        raise LanguageCheckError("Tree-sitter could not analyze the changed source files.")
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise LanguageCheckError("Tree-sitter returned an invalid analysis result.") from error
    if not isinstance(parsed, dict) or set(parsed) != set(files):
        raise LanguageCheckError("Tree-sitter returned incomplete analysis for the changed source files.")
    return parsed


def _parse_tree_sitter_request():
    try:
        from tree_sitter import Language, Parser
        request = json.load(sys.stdin)
        result = {}
        for item in request:
            path = item["path"]
            extension = Path(path).suffix.lower()
            if extension in {".yml", ".yaml"}:
                import yaml
                import tree_sitter_bash
                document = yaml.compose(item["content"], Loader=yaml.BaseLoader)
                identifiers = []
                pending = [document] if document else []
                visited = set()
                shell_parser = Parser(Language(tree_sitter_bash.language()))
                while pending:
                    current = pending.pop()
                    if id(current) in visited:
                        raise ValueError("YAML aliases require separate analysis")
                    visited.add(id(current))
                    if isinstance(current, yaml.MappingNode):
                        seen = set()
                        for key, value in current.value:
                            if not isinstance(key, yaml.ScalarNode) or key.value in seen or key.value == "<<":
                                raise ValueError("ambiguous YAML mapping")
                            seen.add(key.value)
                            identifiers.append({"line": key.start_mark.line + 1, "name": key.value})
                            if key.value == "run" and isinstance(value, yaml.ScalarNode):
                                if value.style != "|" and (value.end_mark.line > value.start_mark.line or "\n" in value.value):
                                    raise ValueError("multiline workflow commands require literal block syntax")
                                first_line = value.start_mark.line + (2 if value.style == "|" else 1)
                                def replace_expression(match):
                                    expression = match.group(1).strip()
                                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+", expression):
                                        raise ValueError("unsupported workflow expression")
                                    identifiers.append({"line": first_line + value.value.count("\n", 0, match.start()), "name": expression})
                                    return "workflow_expression"
                                shell_source = re.sub(r"\$\{\{(.*?)\}\}", replace_expression, value.value)
                                shell_tree = shell_parser.parse(shell_source.encode("utf-8"))
                                if shell_tree.root_node.has_error:
                                    raise ValueError("unsupported embedded shell")
                                nodes = [shell_tree.root_node]
                                while nodes:
                                    node = nodes.pop()
                                    if node.type in {"variable_name", "function_name"}:
                                        identifiers.append({"line": first_line + node.start_point.row, "name": node.text.decode("utf-8")})
                                    nodes.extend(node.children)
                            pending.append(value)
                    elif isinstance(current, yaml.SequenceNode):
                        pending.extend(current.value)
                result[path] = identifiers
                continue
            module_name, language_name = TREE_SITTER_LANGUAGES[extension]
            module = __import__(module_name)
            if language_name == "php":
                grammar = Language(module.language_php())
            elif language_name == "tsx":
                grammar = Language(module.language_tsx())
            elif language_name == "typescript":
                grammar = Language(module.language_typescript())
            else:
                grammar = Language(module.language())
            source = item["content"].encode("utf-8")
            tree = Parser(grammar).parse(source)
            if tree.root_node.has_error:
                raise ValueError("parse error")
            identifiers = []
            stack = [tree.root_node]
            while stack:
                node = stack.pop()
                if extension in {".sh", ".bash"}:
                    if node.type in {"variable_name", "function_name"} or (node.parent and node.parent.type == "function_definition" and node.parent.child_by_field_name("name") == node):
                        identifiers.append({"line": node.start_point.row + 1, "name": node.text.decode("utf-8")})
                    stack.extend(reversed(node.children))
                    continue
                if extension == ".css":
                    authored_name = node.type in {"class_name", "id_name", "keyframes_name"}
                    custom_property = node.type == "property_name" and node.text.startswith(b"--")
                    custom_reference = node.type == "plain_value" and node.text.startswith(b"--")
                    if authored_name or custom_property or custom_reference:
                        identifiers.append({"line": node.start_point.row + 1, "name": node.text.decode("utf-8")})
                    stack.extend(reversed(node.children))
                    continue
                if node.child_count == 0 and node.type in {
                    "identifier", "property_identifier", "private_property_identifier",
                    "shorthand_property_identifier", "shorthand_property_identifier_pattern",
                    "type_identifier", "field_identifier", "variable_name", "name",
                    "namespace_name", "named_label", "constant", "class_name",
                }:
                    value = source[node.start_byte:node.end_byte].decode("utf-8")
                    identifiers.append({"line": node.start_point.row + 1, "name": value})
                if node.type in {"pair", "property_assignment", "pair_pattern"} and node.named_child_count:
                    key_node = node.named_children[0]
                    if key_node.type in {"string", "string_content"}:
                        key_value = key_node.text.decode("utf-8").strip("'\"` ")
                        if key_value:
                            identifiers.append({"line": key_node.start_point.row + 1, "name": key_value})
                if node.type == "subscript_expression" and node.named_child_count > 1:
                    key_node = node.named_children[-1]
                    if key_node.type == "string":
                        key_value = key_node.text.decode("utf-8").strip("'\"` ")
                        if key_value:
                            identifiers.append({"line": key_node.start_point.row + 1, "name": key_value})
                if node.type in {"scoped_call_expression", "member_call_expression"}:
                    call_names = {child.text.decode("utf-8") for child in node.named_children if child.type == "name"}
                    argument_list = next((child for child in node.named_children if child.type == "arguments"), None)
                    if call_names.intersection({"make", "create"}) and argument_list and argument_list.named_child_count:
                        string_node = next((child for child in argument_list.named_children[0].named_children
                                            if child.type in {"encapsed_string", "string"}), None)
                        if string_node:
                            key_value = ("".join(child.text.decode("utf-8") for child in string_node.named_children
                                                  if child.type == "string_content") if string_node.type == "encapsed_string"
                                         else string_node.text.decode("utf-8").strip("'\""))
                            if key_value:
                                identifiers.append({"line": string_node.start_point.row + 1, "name": key_value})
                if node.type == "array_element_initializer" and any(child.type == "=>" for child in node.children):
                    key_node = node.named_children[0] if node.named_children else None
                    if key_node and key_node.type not in {"encapsed_string", "string"}:
                        key_node = None
                    if key_node:
                        key_value = ("".join(child.text.decode("utf-8") for child in key_node.named_children
                                              if child.type == "string_content") if key_node.type == "encapsed_string"
                                     else key_node.text.decode("utf-8").strip("'\""))
                        if key_value:
                            identifiers.append({"line": key_node.start_point.row + 1, "name": key_value})
                stack.extend(reversed(node.children))
            result[path] = identifiers
    except Exception:
        return 2
    print(json.dumps(result))
    return 0


def _python_identifiers(content, path):
    try:
        tree = ast.parse(content, filename=path)
    except (SyntaxError, ValueError) as error:
        raise LanguageCheckError(f"Cannot parse changed Python file '{path}'.") from error
    identifiers = []
    for node in ast.walk(tree):
        for field_name in ("id", "arg", "attr", "name", "asname", "module", "rest"):
            value = getattr(node, field_name, None)
            if isinstance(value, str) and value:
                identifiers.append((node.lineno, value))
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            identifiers.extend((node.lineno, name) for name in node.names)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            parent = getattr(node, "_parent", None)
            if isinstance(parent, ast.Subscript) and parent.slice is node:
                identifiers.append((node.lineno, node.value))
            elif isinstance(parent, ast.Dict) and node in parent.keys and "." not in node.value and "/" not in node.value:
                identifiers.append((node.lineno, node.value))
        for child in ast.iter_child_nodes(node):
            child._parent = node
    return identifiers


def _config_identifiers(content, path):
    extension = Path(path).suffix.lower()
    try:
        value = json.loads(content) if extension == ".json" else tomllib.loads(content)
    except (ValueError, tomllib.TOMLDecodeError) as error:
        raise LanguageCheckError(f"Cannot parse changed configuration file '{path}'.") from error
    if extension == ".json":
        matches = list(JSON_KEY_PATTERN.finditer(content))
        structural_keys = _mapping_keys(value)
        if len(matches) != len(structural_keys):
            raise LanguageCheckError(f"Cannot locate every structural key in changed configuration file '{path}'.")
        identifiers = []
        key_paths = _json_key_paths(value)
        for match, key_path in zip(matches, key_paths):
            try:
                name = json.loads('"' + match.group(1) + '"')
            except json.JSONDecodeError as error:
                raise LanguageCheckError(f"Cannot decode a JSON key in '{path}'.") from error
            if not _external_package_key(value, path, key_path):
                identifiers.append((content.count("\n", 0, match.start()) + 1, name))
        return identifiers
    return _toml_key_identifiers(content, path, value)


def _json_key_paths(value, prefix=()):
    paths = []
    if isinstance(value, dict):
        for key, child in value.items():
            current = prefix + (key,)
            paths.append(current)
            paths.extend(_json_key_paths(child, current))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_json_key_paths(child, prefix + (index,)))
    return paths


def _external_package_key(value, path, key_path):
    """Recognize npm schema positions, never exempt an entire generated file."""
    filename = Path(path).name
    if filename not in {"package.json", "package-lock.json"} or not isinstance(value, dict):
        return False
    dependency_maps = {"dependencies", "devDependencies", "optionalDependencies", "peerDependencies", "peerDependenciesMeta"}
    if filename == "package.json":
        return len(key_path) == 2 and key_path[0] in dependency_maps
    if value.get("lockfileVersion") not in {2, 3} or not isinstance(value.get("packages"), dict):
        return False
    if len(key_path) == 2 and key_path[0] == "packages":
        return key_path[1] == "" or str(key_path[1]).startswith("node_modules/")
    if len(key_path) == 4 and key_path[0] == "packages" and key_path[2] in dependency_maps:
        return True
    # Executable and engine names are contracts in dependency manifests only.
    return len(key_path) == 4 and key_path[0] == "packages" and bool(key_path[1]) and key_path[2] in {"bin", "engines", "funding"}


def _mapping_keys(value, prefix=()):
    keys = []
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                key_path = prefix + (key,)
                keys.append((".".join(key_path), key))
                keys.extend(_mapping_keys(child, key_path))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_mapping_keys(item, prefix))
    return keys


def _toml_key_identifiers(content, path, value):
    identifiers = []
    multiline = None
    for line_number, original_line in enumerate(content.splitlines(), start=1):
        line, multiline = _mask_toml_strings(original_line, multiline)
        if line is None:
            continue
        if original_line.lstrip().startswith("["):
            line, _ = _mask_toml_strings(original_line, preserve_header=True)
        section = re.match(r"^\s*\[\[?\s*(.*?)\s*\]\]?\s*$", line)
        if section:
            identifiers.extend((line_number, token) for token in _toml_key_parts(section.group(1)))
            continue
        pattern = re.compile(r"(?:^|[{,])\s*(\"(?:\\.|[^\"])*\"|'[^']*'|[A-Za-z0-9_-]+(?:\s*\.\s*(?:\"(?:\\.|[^\"])*\"|'[^']*'|[A-Za-z0-9_-]+))*)\s*=")
        for match in pattern.finditer(line):
            identifiers.extend((line_number, token) for token in _toml_key_parts(match.group(1)))
    actual_keys = Counter(key for _, key in _mapping_keys(value))
    extracted_keys = Counter(name for _, name in identifiers)
    if any(extracted_keys[key] < count for key, count in actual_keys.items()):
        raise LanguageCheckError(f"Cannot locate every structural key in changed TOML file '{path}'.")
    return identifiers


def _mask_toml_strings(line, multiline=None, preserve_header=False):
    characters = list(line)
    index = 0
    if multiline:
        closing = line.find(multiline)
        if closing < 0:
            return None, multiline
        for position in range(closing + 3):
            characters[position] = " "
        index = closing + 3
        multiline = None
    while index < len(line):
        if line[index] == "#":
            for position in range(index, len(line)):
                characters[position] = " "
            break
        if line[index] not in ("'", '"'):
            index += 1
            continue
        delimiter = line[index:index + 3] if line.startswith(('"""', "'''"), index) else line[index]
        cursor = index + len(delimiter)
        while cursor < len(line):
            if line.startswith(delimiter, cursor):
                break
            if delimiter.startswith('"') and line[cursor] == "\\":
                cursor += 2
            else:
                cursor += 1
        if cursor >= len(line):
            if len(delimiter) == 3:
                for position in range(index, len(line)):
                    characters[position] = " "
                return "".join(characters), delimiter
            raise LanguageCheckError("Cannot locate the end of a TOML string.")
        after = cursor + len(delimiter)
        next_significant = after
        while next_significant < len(line) and line[next_significant].isspace():
            next_significant += 1
        is_key = next_significant < len(line) and line[next_significant] in "=."
        if preserve_header and line.lstrip().startswith("["):
            is_key = True
        if not is_key:
            for position in range(index, after):
                characters[position] = " "
        index = after
    return "".join(characters), multiline


def _toml_key_parts(value):
    return [part.strip().strip("'\"") for part in re.split(r"\s*\.\s*", value) if part.strip()]


def _path_tokens(path):
    parts = path.replace("\\", "/").split("/")
    tokens = []
    for part in parts:
        if not part:
            continue
        name = re.sub(r"\.[A-Za-z0-9]+$", "", part)
        tokens.extend(_tokens_for_name(name))
    return tokens


def _check_identifiers(path, identifiers, added_lines, dictionary):
    diagnostics = []
    for line_number, value in identifiers:
        if line_number not in added_lines:
            continue
        for token in _tokens_for_name(value):
            if not is_english_word(token, dictionary):
                diagnostics.append(
                    f"{path}:{line_number}: identifier '{token}' is unknown to the bundled English dictionary. "
                    "Use an English identifier or add a narrowly scoped technical term."
                )
    return diagnostics


def validate_changes(changed_files, graphify_binary=None):
    """Validate `{path, content, added_lines, path_changed}` records from a PR diff."""
    dictionary = load_dictionary()
    diagnostics = []
    tree_sitter_sources = {}
    for changed_file in changed_files:
        path = changed_file["path"]
        content = changed_file.get("content")
        if changed_file.get("path_changed"):
            diagnostics.extend(_check_identifiers(path, [(1, token) for token in _path_tokens(path)], {1}, dictionary))
        if content is None:
            continue
        extension = Path(path).suffix.lower()
        if path.lower().endswith(".blade.php"):
            raise LanguageCheckError(f"Cannot verify changed code file '{path}': Blade syntax is unsupported.")
        if extension not in SUPPORTED_EXTENSIONS:
            raise LanguageCheckError(f"Cannot verify changed code file '{path}': unsupported language.")
        if not isinstance(content, str):
            raise LanguageCheckError(f"Cannot decode changed code file '{path}'.")
        added_lines = changed_file.get("added_lines")
        if not isinstance(added_lines, (set, list, tuple)):
            raise LanguageCheckError(f"Cannot verify changed lines in '{path}'.")
        if extension == ".py":
            identifiers = _python_identifiers(content, path)
        elif extension in (".json", ".toml"):
            identifiers = _config_identifiers(content, path)
        else:
            tree_sitter_sources[path] = content
            identifiers = []
        diagnostics.extend(_check_identifiers(path, identifiers, set(added_lines), dictionary))
    parsed_sources = _parse_tree_sitter_files(tree_sitter_sources, graphify_binary)
    for changed_file in changed_files:
        path = changed_file["path"]
        if path in parsed_sources:
            identifiers = [(item["line"], item["name"]) for item in parsed_sources[path]]
            diagnostics.extend(_check_identifiers(path, identifiers, set(changed_file["added_lines"]), dictionary))
    return list(dict.fromkeys(diagnostics))


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "parse-tree-sitter":
    raise SystemExit(_parse_tree_sitter_request())

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
SUPPORTED_EXTENSIONS.add(".blade.php")
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
    # Exact ctypes and Win32 SDK type/function signature contracts.
    "argtypes", "byref", "ctypes", "dll", "dword", "restype", "wintypes",
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
    # Exact PHP and export-format contracts found in supported application code.
    "auth", "authenticatable", "basename", "bom", "canonicalizing", "compatibilities",
    "csv", "downloader", "downloaders", "enum", "enums", "eol", "fclose", "fflush",
    "fopen", "fpassthru", "fwrite", "isset", "matchable", "md5", "pdo", "stringable",
    "stringify", "strlen", "strtolower", "symfony", "tempnam", "throwable", "xlsx",
    # PHP namespace/type syntax and Python parsing/mapping contracts used by this analyzer.
    "classmethod", "iterable", "namespaces", "setdefault",
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


_BLADE_DIRECTIVES_WITH_ARGUMENTS = {
    "auth", "can", "cannot", "cannotany", "canany", "checked", "class", "component",
    "else", "elseif", "env", "error", "extends", "foreach", "guest", "if",
    "isset", "json", "method", "props", "selected", "section", "slot", "switch", "unless",
    "unset", "unlessguest", "while", "include", "includeif", "includewhen", "includeunless",
    "includefirst", "each", "aware", "pushif", "prependif", "pushonce", "once", "use",
}
_BLADE_DIRECTIVES_WITHOUT_ARGUMENTS = {
    "else", "endif", "endunless", "endisset", "endempty", "endauth", "endcan", "endcannot",
    "endcanany", "endguest", "endproduction", "endenv", "endsection", "show", "stop", "append",
    "overwrite", "parent", "endpush", "endprepend", "endpushonce", "endonce", "break", "continue",
    "endforeach", "endwhile", "default", "endswitch", "endphp", "endcomponent",
    "endverbatim", "csrf", "production", "stack",
}
_BLADE_END_IF = "endif"
_BLADE_END_UNLESS = "endunless"
_BLADE_END_FOR_EACH = "endforeach"
_BLADE_END_WHILE = "endwhile"
_BLADE_END_SWITCH = "endswitch"


_BLADE_SCRIPT_TAG = re.compile(r"<\s*/?\s*script\b", re.I)
_BLADE_SCRIPT_OPEN = re.compile(r"""<script(?:\s+type\s*=\s*(?:"(?:module|text/javascript)"|'(?:module|text/javascript)'))?\s*>""", re.I)
_BLADE_SCRIPT_CLOSE = re.compile(r"</\s*script\b[^>]*>", re.I)
_BLADE_SCRIPT_WRAPPER = re.compile(r"@script\b")
_BLADE_SCRIPT_WRAPPER_END = re.compile(r"\s*@endscript\b")
_BLADE_SCRIPT_MARKUP = re.compile(r"<\?|{{--|{{|{!!|@[A-Za-z][A-Za-z0-9_]*")
_BLADE_SCRIPT_JSON = re.compile(r"@json[ \t]*\(")


def _blank_source(content):
    return re.sub(r"[^\n]", " ", content)


def _blade_expression_end(content, start):
    """Find the end of a parenthesized PHP expression without running PHP."""
    depth = 1
    quote = None
    cursor = start
    while cursor < len(content):
        character = content[cursor]
        pair = content[cursor:cursor + 2]
        if quote:
            if character == "\\":
                cursor += 2
                continue
            if character == quote:
                quote = None
        elif pair == "/*":
            close = content.find("*/", cursor + 2)
            if close < 0:
                return None
            cursor = close + 2
            continue
        elif pair == "//" or character == "#" and pair != "#[":
            close = content.find("\n", cursor + 1)
            if close < 0:
                return None
            cursor = close + 1
            continue
        elif character in "\"'`":
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    return None


def _blade_script_source(content, index, path):
    """Project one supported script into separate JavaScript and PHP sources."""
    wrapper = _BLADE_SCRIPT_WRAPPER.match(content, index)
    tag_start = index
    if wrapper:
        tag_start = len(content) - len(content[wrapper.end():].lstrip())
    opening = _BLADE_SCRIPT_OPEN.match(content, tag_start)
    if not opening:
        raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': unsupported script opening.")
    closing = _BLADE_SCRIPT_CLOSE.search(content, opening.end())
    if not closing or not re.fullmatch(r"</script\s*>", closing.group(), re.I):
        raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': malformed or unclosed script block.")
    end = closing.end()
    if wrapper:
        wrapper_end = _BLADE_SCRIPT_WRAPPER_END.match(content, end)
        if not wrapper_end:
            raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': expected @endscript after the script.")
        end = wrapper_end.end()

    body = content[opening.end():closing.start()]
    javascript = ["\n" * content.count("\n", 0, opening.end())]
    php = [_blank_source(content[index:opening.end()])]
    expressions = []
    offset = len(javascript[0])
    cursor = 0
    while marker := _BLADE_SCRIPT_MARKUP.search(body, cursor):
        directive = _BLADE_SCRIPT_JSON.match(body, marker.start())
        if not directive:
            raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': unsupported Blade syntax inside JavaScript.")
        close_at = _blade_expression_end(body, directive.end())
        if close_at is None or not body[directive.end():close_at].strip():
            raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': malformed @json expression.")
        preceding = body[cursor:marker.start()]
        javascript.append(preceding)
        php.append(_blank_source(preceding))
        offset += len(preceding.encode("utf-8"))
        expressions.append(offset)
        expression = body[directive.end():close_at]
        replacement = "null" + "\n" * expression.count("\n")
        javascript.append(replacement)
        php.append("<?php json_encode(" + expression + "); ?>")
        offset += len(replacement)
        cursor = close_at + 1

    javascript.append(body[cursor:])
    php.append(_blank_source(body[cursor:] + content[closing.start():end]))
    return end, "".join(php), ("".join(javascript), expressions)


def _blade_sources(content, path):
    """Expose Blade PHP and JavaScript while retaining original line numbers."""
    replacements = []
    scripts = []

    def replace(start, end, replacement):
        if content[start:end].count("\n") != replacement.count("\n"):
            raise LanguageCheckError(f"Cannot preserve source lines while analyzing Blade file '{path}'.")
        replacements.append((start, end, replacement))

    def find_delimiter(start, delimiter):
        quote = None
        escaped = False
        line_comment = False
        block_comment = False
        for position in range(start, len(content)):
            pair = content[position:position + 2]
            if line_comment:
                if content[position] == "\n":
                    line_comment = False
                continue
            if block_comment:
                if pair == "*/":
                    block_comment = False
                continue
            if quote:
                if escaped:
                    escaped = False
                elif content[position] == "\\":
                    escaped = True
                elif content[position] == quote:
                    quote = None
                continue
            if pair == "//" or content[position] == "#":
                line_comment = True
                continue
            if pair == "/*":
                block_comment = True
                continue
            if content[position] in "\"'`":
                quote = content[position]
                continue
            if content.startswith(delimiter, position):
                return position
        return None

    index = 0
    directive_stack = []
    while index < len(content):
        if content.startswith("{{--", index):
            close = content.find("--}}", index + 4)
            if close < 0:
                raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': unclosed Blade comment.")
            end = close + 4
            comment = content[index:end]
            neutralized = "".join("\n" if character == "\n" else " " for character in comment)
            replace(index, end, neutralized)
            index = end
            continue
        if content.startswith("@@", index):
            index += 2
            continue
        if _BLADE_SCRIPT_TAG.match(content, index) or _BLADE_SCRIPT_WRAPPER.match(content, index):
            end, php, script = _blade_script_source(content, index, path)
            replace(index, end, php)
            scripts.append(script)
            index = end
            continue
        if content[index] == ":" and index > 0 and content[index - 1] in " \t\n":
            binding = re.match(r":([A-Za-z][A-Za-z0-9_-]*)\s*=\s*([\"'])(.*?)\2", content[index:], re.S)
            if binding:
                value_start = index + binding.start(3)
                value_end = index + binding.end(3)
                replace(value_start - 1, value_start, "<?php ")
                replace(value_end, value_end + 1, "; ?>")
                index = value_end + 1
                continue
            if re.match(r":[A-Za-z][A-Za-z0-9_-]*\s*=", content[index:]):
                raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': malformed bound attribute.")
        if content.startswith("{{", index) or content.startswith("{!!", index):
            opening = 3 if content.startswith("{!!", index) else 2
            closing = "!!}" if opening == 3 else "}}"
            close_at = find_delimiter(index + opening, closing)
            if close_at is None:
                raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': unclosed echo expression.")
            replace(index, index + opening, "<?php ")
            replace(close_at, close_at + len(closing), "; ?>")
            index = close_at + len(closing)
            continue
        if content.startswith("@php", index) and (index + 4 == len(content) or not content[index + 4].isalnum()):
            close_at = find_delimiter(index + 4, "@endphp")
            if close_at is None:
                raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': unclosed @php block.")
            block_start = index + 4
            block_end = close_at
            replace(block_end, block_end + len("@endphp"), "?>")
            replace(index, block_start, "<?php")
            index = block_end + len("@endphp")
            continue
        if content[index] == "@":
            directive = re.match(r"@([A-Za-z][A-Za-z0-9_]*)", content[index:])
            if directive:
                name = directive.group(1).lower()
                end = index + directive.end()
                if name == "forelse":
                    raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': @forelse control syntax is unsupported.")
                if name in {"php", "endphp", "verbatim", "endverbatim"}:
                    raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': unsupported @{name} block.")
                if name not in _BLADE_DIRECTIVES_WITH_ARGUMENTS and name not in _BLADE_DIRECTIVES_WITHOUT_ARGUMENTS:
                    raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': unsupported @{name} directive.")
                if name in _BLADE_DIRECTIVES_WITH_ARGUMENTS:
                    cursor = end
                    while cursor < len(content) and content[cursor].isspace():
                        cursor += 1
                    if cursor >= len(content) or content[cursor] != "(":
                        if name in {"else"}:
                            index = end
                            continue
                        if name in _BLADE_DIRECTIVES_WITHOUT_ARGUMENTS:
                            index = end
                            continue
                        raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': @{name} directive has no parseable expression.")
                    if name in {"for", "forelse"}:
                        raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': @{name} control syntax is unsupported.")
                    depth = 0
                    quote = None
                    escaped = False
                    close_at = None
                    for position in range(cursor, len(content)):
                        character = content[position]
                        if quote:
                            if escaped:
                                escaped = False
                            elif character == "\\":
                                escaped = True
                            elif character == quote:
                                quote = None
                            continue
                        if character in "\"'`":
                            quote = character
                        elif character == "(":
                            depth += 1
                        elif character == ")":
                            depth -= 1
                            if depth == 0:
                                close_at = position
                                break
                    if close_at is None or quote:
                        raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': malformed @{name} expression.")
                    if name in {"if", "unless", "foreach", "while", "switch"}:
                        directive_stack.append(name)
                    prefix = "<?php "
                    suffix = "; ?>"
                    if name in {"if", "elseif", "unless", "while", "foreach", "switch", "can", "cannot", "canany", "cannotany"}:
                        keyword = "if" if name == "unless" else name
                        expression = content[cursor + 1:close_at]
                        if name == "unless":
                            expression = "! (" + expression + ")"
                        prefix = "<?php " + keyword + " ("
                        suffix = "): ?>" if name in {"if", "elseif", "unless", "while", "foreach", "switch"} else "; ?>"
                    replace(index, cursor + 1, prefix)
                    replace(close_at, close_at + 1, suffix)
                    index = close_at + 1
                    continue
                cursor = end
                while cursor < len(content) and content[cursor].isspace():
                    cursor += 1
                if cursor < len(content) and content[cursor] == "(":
                    raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': @{name} does not accept arguments.")
                if name in {"else", _BLADE_END_IF, _BLADE_END_UNLESS, _BLADE_END_FOR_EACH, _BLADE_END_WHILE, _BLADE_END_SWITCH}:
                    expected = {_BLADE_END_IF: {"if", "unless"}, _BLADE_END_UNLESS: {"unless"}, _BLADE_END_FOR_EACH: {"foreach"},
                                _BLADE_END_WHILE: {"while"}, _BLADE_END_SWITCH: {"switch"}}
                    if name in expected:
                        if not directive_stack or directive_stack[-1] not in expected[name]:
                            raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': unmatched @{name} directive.")
                        directive_stack.pop()
                    statement = {"else": "else:", _BLADE_END_IF: "endif;", _BLADE_END_UNLESS: "endif;",
                                 _BLADE_END_FOR_EACH: "endforeach;", _BLADE_END_WHILE: "endwhile;",
                                 _BLADE_END_SWITCH: "endswitch;"}[name]
                    replace(index, end, "<?php " + statement + " ?>")
                index = end
                continue
        index += 1
    if directive_stack:
        raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': unclosed @{directive_stack[-1]} directive.")
    output = content
    for start, end, replacement in sorted(replacements, reverse=True):
        output = output[:start] + replacement + output[end:]
    if re.search(r"<\s*/?\s*style\b|\s(?:x-[\w:-]+|on[a-z]+)\s*=|\s+wire:[\w.-]+\s*=\s*(?:[^\"']|[\"']\s*[^\"'])", output, re.I):
        raise LanguageCheckError(f"Cannot verify changed Blade file '{path}': embedded CSS, JavaScript handlers or Alpine expressions are unsupported.")
    return output, scripts


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


def _parse_tree_sitter_files(files, graphify_binary, expression_offsets):
    if not files:
        return {}
    interpreter = _tree_sitter_interpreter(graphify_binary)
    request = [
        {"path": path, "content": content, "expression_offsets": expression_offsets.get(path, [])}
        for path, content in files.items()
    ]
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
            workbook_row_helpers = _workbook_row_helper_names(tree.root_node)
            workbook_row_variables = _workbook_row_variables(tree.root_node, workbook_row_helpers)
            identifiers = []
            expression_offsets = set(item.get("expression_offsets", []))
            stack = [tree.root_node]
            while stack:
                node = stack.pop()
                if node.type == "null":
                    expression_offsets.discard(node.start_byte)
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
                    livewire_assertion = (
                        extension == ".php"
                        and value == "assertDontSeeHtml"
                        and "tests" in Path(path).parts
                        and node.parent.type == "member_call_expression"
                        and node.parent.child_by_field_name("name") == node
                    )
                    if not livewire_assertion:
                        identifiers.append({"line": node.start_point.row + 1, "name": value})
                if node.type in {"pair", "property_assignment", "pair_pattern"} and node.named_child_count:
                    key_node = node.named_children[0]
                    if key_node.type in {"string", "string_content"}:
                        key_value = key_node.text.decode("utf-8").strip("'\"` ")
                        if key_value:
                            identifiers.append({"line": key_node.start_point.row + 1, "name": key_value})
                if node.type == "subscript_expression" and node.named_child_count > 1:
                    key_node = node.named_children[-1]
                    if key_node.type == "string" and not _is_workbook_row_access(node, workbook_row_variables):
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
                    if key_node and not _is_workbook_row_expectation(node, workbook_row_variables) \
                        and not _is_workbook_sheet_name_key(node):
                        key_value = ("".join(child.text.decode("utf-8") for child in key_node.named_children
                                              if child.type == "string_content") if key_node.type == "encapsed_string"
                                     else key_node.text.decode("utf-8").strip("'\""))
                        if key_value:
                            identifiers.append({"line": key_node.start_point.row + 1, "name": key_value})
                stack.extend(reversed(node.children))
            if expression_offsets:
                raise ValueError("Blade JSON must occupy a JavaScript expression")
            result[path] = identifiers
    except Exception:
        return 2
    print(json.dumps(result))
    return 0


def _tree_descendants(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def _same_scope_descendants(node):
    stack = [node]
    nested_scopes = {"function_definition", "method_declaration", "anonymous_function", "arrow_function"}
    while stack:
        current = stack.pop()
        yield current
        if current is not node and current.type in nested_scopes:
            continue
        stack.extend(reversed(current.named_children))


def _call_name(node):
    if node.type not in {"function_call_expression", "scoped_call_expression"} or not node.named_children:
        return None
    name_node = node.named_children[0]
    return name_node.text.decode("utf-8") if name_node.type in {"name", "variable_name"} else None


def _call_arguments(node):
    return next((child for child in node.named_children if child.type == "arguments"), None)


def _argument_values(node):
    arguments = _call_arguments(node)
    return [argument.named_children[0] for argument in arguments.named_children if argument.named_children] if arguments else []


def _variable_name(node):
    return node.text.decode("utf-8") if node.type == "variable_name" else None


def _assigned_variable(node):
    if node.type != "assignment_expression" or len(node.named_children) < 2:
        return None
    return _variable_name(node.named_children[0])


def _enclosing_scope(node):
    current = node.parent
    while current:
        if current.type in {"function_definition", "method_declaration", "anonymous_function", "arrow_function"}:
            return current.start_byte
        current = current.parent
    return 0


def _has_namespace_ancestor(node):
    current = node.parent
    while current:
        if current.type == "namespace_definition":
            return True
        current = current.parent
    return False


def _contains_namespace_definition(root):
    return any(node.type == "namespace_definition" for node in _tree_descendants(root))


def _has_workbook_rows_source(function_node):
    """Recognize only helpers that turn the visible first worksheet row into map keys."""
    assignments_by_variable = {}
    assignments = []

    for node in _same_scope_descendants(function_node):
        if node.type != "assignment_expression" or len(node.named_children) < 2:
            continue

        left, right = node.named_children[:2]
        left_name = _variable_name(left)
        if left_name:
            assignments_by_variable.setdefault(left_name, []).append(node)
        assignments.append((node, left_name, right))

    rows_assignments = []
    for node, left_name, right in assignments:
        if right.type == "member_call_expression":
            method_names = [child.text.decode("utf-8") for child in right.named_children if child.type == "name"]
            if "toArray" in method_names and any(
                descendant.type == "member_call_expression"
                and "getSheetByName" in [child.text.decode("utf-8") for child in descendant.named_children if child.type == "name"]
                for descendant in _tree_descendants(right)
            ):
                if left_name:
                    rows_assignments.append((node, left_name))

    if len(rows_assignments) != 1:
        return False

    rows_assignment, rows_variable = rows_assignments[0]
    if len(assignments_by_variable.get(rows_variable, [])) != 1:
        return False

    headers_assignments = []
    for node, left_name, right in assignments:
        if _call_name(right) == "array_shift":
            values = _argument_values(right)
            if left_name and len(values) == 1 and _variable_name(values[0]) == rows_variable:
                headers_assignments.append((node, left_name))

    if len(headers_assignments) != 1:
        return False

    headers_assignment, headers_variable = headers_assignments[0]
    if rows_variable == headers_variable or len(assignments_by_variable.get(headers_variable, [])) != 1 \
        or rows_assignment.end_byte > headers_assignment.start_byte:
        return False

    return_statements = [
        node for node in _same_scope_descendants(function_node)
        if node.type == "return_statement" and node.named_children
    ]
    if len(return_statements) != 1 or return_statements[0].start_byte < headers_assignment.end_byte:
        return False

    returned = return_statements[0].named_children[0]
    if _call_name(returned) != "array_map":
        return False

    arguments = _argument_values(returned)
    if len(arguments) != 2 or _variable_name(arguments[1]) != rows_variable:
        return False

    mapper = arguments[0]
    for call in _tree_descendants(mapper):
        if _call_name(call) != "array_combine":
            continue
        combine_arguments = _argument_values(call)
        if len(combine_arguments) == 2 and _variable_name(combine_arguments[0]) == headers_variable:
            return True

    return False


def _workbook_row_helper_names(root):
    if _contains_namespace_definition(root):
        return set()

    declarations = {}
    for node in _tree_descendants(root):
        if node.type != "function_definition" or not node.named_children:
            continue
        if _has_namespace_ancestor(node):
            continue
        name_node = next((child for child in node.named_children if child.type == "name"), None)
        body = next((child for child in node.named_children if child.type == "compound_statement"), None)
        if name_node:
            name = name_node.text.decode("utf-8")
            declarations.setdefault(name, []).append(bool(body and _has_workbook_rows_source(body)))

    return {
        name for name, declarations_for_name in declarations.items()
        if len(declarations_for_name) == 1 and declarations_for_name[0]
    }


def _is_exporter_row_mapping(node):
    if _call_name(node) != "array_combine":
        return None
    arguments = _argument_values(node)
    if len(arguments) != 2 or _call_name(arguments[0]) != "array_values":
        return None
    column_arguments = _argument_values(arguments[0])
    exporter_call = arguments[1]
    if len(column_arguments) != 1 or _variable_name(column_arguments[0]) is None \
        or exporter_call.type != "function_call_expression" or not exporter_call.named_children \
        or exporter_call.named_children[0].type != "variable_name":
        return None
    return _variable_name(column_arguments[0]), _variable_name(exporter_call.named_children[0])


def _export_columns_assignment(node):
    if node.type != "assignment_expression" or len(node.named_children) < 2:
        return None
    variable = _variable_name(node.named_children[0])
    value = node.named_children[1]
    if not variable or value.type != "member_call_expression":
        return None
    calls = [
        child.text.decode("utf-8")
        for descendant in _tree_descendants(value)
        for child in descendant.named_children
        if child.type == "name"
        and child.text.decode("utf-8") in {"getColumns", "mapWithKeys", "getName", "getLabel"}
    ]
    required_calls = {"getColumns", "mapWithKeys", "getName", "getLabel"}
    return variable if required_calls.issubset(calls) else None


def _exporter_assignment(node):
    if node.type != "assignment_expression" or len(node.named_children) < 2:
        return None
    variable = _variable_name(node.named_children[0])
    value = node.named_children[1]
    if not variable or value.type != "object_creation_expression" or not value.named_children:
        return None
    class_name = value.named_children[0]
    if class_name.type != "name" or not class_name.text.decode("utf-8").endswith("Exporter"):
        return None
    columns = {
        item.text.decode("utf-8")
        for argument in _argument_values(value)
        for item in _tree_descendants(argument)
        if item.type == "variable_name"
    }
    return variable, columns


def _workbook_row_variables(root, helper_names):
    variables = {}
    columns_by_scope = set()
    exporters_by_scope = {}
    csv_readers_with_headers = set()
    nodes = list(_tree_descendants(root))
    has_namespaces = any(node.type == "namespace_definition" for node in nodes)
    assignment_counts = {}

    for node in nodes:
        variable = _assigned_variable(node)
        if variable:
            scope = _enclosing_scope(node)
            key = (scope, variable)
            assignment_counts[key] = assignment_counts.get(key, 0) + 1

    for node in nodes:
        scope = _enclosing_scope(node)
        if node.type == "member_call_expression":
            method_name = next((child.text.decode("utf-8") for child in node.named_children if child.type == "name"), None)
            receiver = node.named_children[0] if node.named_children else None
            if method_name == "setHeaderOffset" and receiver and _variable_name(receiver):
                csv_readers_with_headers.add((scope, _variable_name(receiver)))

        variable = _assigned_variable(node)
        if not variable or len(node.named_children) < 2:
            continue

        value = node.named_children[1]
        columns_variable = _export_columns_assignment(node)
        if columns_variable:
            columns_by_scope.add((scope, columns_variable))
        else:
            columns_by_scope.discard((scope, variable))

        exporter = _exporter_assignment(node)
        if exporter:
            exporter_columns = {
                column for column in exporter[1]
                if (scope, column) in columns_by_scope
            }
            if exporter_columns:
                exporters_by_scope[(scope, exporter[0])] = exporter_columns
            else:
                exporters_by_scope.pop((scope, exporter[0]), None)
        else:
            exporters_by_scope.pop((scope, variable), None)

        csv_readers_with_headers.discard((scope, variable))
        source_is_output = _is_output_row_source(
            value,
            scope,
            helper_names,
            not has_namespaces and not _has_namespace_ancestor(node),
            variables,
            csv_readers_with_headers,
            columns_by_scope,
            exporters_by_scope,
        )
        if source_is_output:
            variables[(scope, variable)] = node.end_byte
        else:
            variables.pop((scope, variable), None)

    return {
        key: position
        for key, position in variables.items()
        if assignment_counts.get(key) == 1
    }


def _is_output_row_source(value, scope, helper_names, allow_global_helper, variables, csv_readers, columns, exporters):
    if allow_global_helper and _call_name(value) in helper_names:
        return True

    if value.type == "subscript_expression" and value.named_children:
        base = value.named_children[0]
        if (allow_global_helper and _call_name(base) in helper_names) \
            or _scope_has_row_variable(base, variables, value.start_byte):
            return True

    if _call_name(value) == "iterator_to_array":
        arguments = _argument_values(value)
        records = arguments[0] if arguments else None
        receiver = records.named_children[0] if records and records.type == "member_call_expression" and records.named_children else None
        method_name = next((child.text.decode("utf-8") for child in records.named_children if child.type == "name"), None) if records else None
        if method_name == "getRecords" and receiver and (scope, _variable_name(receiver)) in csv_readers:
            return True

    mapping = next((details for details in _tree_descendants(value) if _is_exporter_row_mapping(details)), None)
    if mapping is None:
        return False
    column_name, exporter_name = _is_exporter_row_mapping(mapping)

    return (scope, column_name) in columns \
        and column_name in exporters.get((scope, exporter_name), set())


def _scope_has_row_variable(node, row_variables, position):
    scope = _enclosing_scope(node)
    current = node
    while current.type == "subscript_expression" and current.named_children:
        current = current.named_children[0]
    if current.type != "variable_name":
        return False
    source_position = row_variables.get((scope, current.text.decode("utf-8")))
    return source_position is not None and position >= source_position


def _is_workbook_row_access(node, row_variables):
    return _scope_has_row_variable(node.named_children[0], row_variables, node.start_byte)


def _is_workbook_row_expectation(node, row_variables):
    parent = node.parent
    while parent:
        if parent.type == "member_call_expression":
            names = [child.text.decode("utf-8") for child in parent.named_children if child.type == "name"]
            if "toMatchArray" in names and parent.named_children:
                receiver = parent.named_children[0]
                if _call_name(receiver) == "expect":
                    arguments = _argument_values(receiver)
                    return len(arguments) == 1 and _scope_has_row_variable(
                        arguments[0], row_variables, arguments[0].start_byte,
                    )
        parent = parent.parent
    return False


def _is_workbook_sheet_name_key(node):
    current = node.parent
    while current and current.type != "foreach_statement":
        current = current.parent

    if current is None or len(current.named_children) < 3:
        return False

    iterable, binding, body = current.named_children[:3]
    if binding.type != "pair" or not binding.named_children:
        return False

    sheet_variable = _variable_name(binding.named_children[0])
    if not sheet_variable:
        return False

    array = node.parent
    while array and array.type != "array_creation_expression":
        array = array.parent
    if array != iterable:
        return False

    for call in _tree_descendants(body):
        if call.type != "member_call_expression":
            continue
        method = next((child.text.decode("utf-8") for child in call.named_children if child.type == "name"), None)
        arguments = _argument_values(call)
        if method == "getSheetByName" and arguments and _variable_name(arguments[0]) == sheet_variable:
            return True

    return False


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
    expression_offsets = {}
    scripts_by_path = {}
    for changed_file in changed_files:
        path = changed_file["path"]
        content = changed_file.get("content")
        if changed_file.get("path_changed"):
            diagnostics.extend(_check_identifiers(path, [(1, token) for token in _path_tokens(path)], {1}, dictionary))
        if content is None:
            continue
        extension = Path(path).suffix.lower()
        is_blade = path.lower().endswith(".blade.php")
        if extension not in SUPPORTED_EXTENSIONS and not is_blade:
            raise LanguageCheckError(f"Cannot verify changed code file '{path}': unsupported language.")
        if not isinstance(content, str):
            raise LanguageCheckError(f"Cannot decode changed code file '{path}'.")
        added_lines = changed_file.get("added_lines")
        if not isinstance(added_lines, (set, list, tuple)):
            raise LanguageCheckError(f"Cannot verify changed lines in '{path}'.")
        if is_blade:
            php_source, scripts = _blade_sources(content, path)
            tree_sitter_sources[path] = php_source
            scripts_by_path[path] = []
            for index, (script, offsets) in enumerate(scripts):
                # A leading slash reserves these internal keys outside repository paths.
                script_path = f"/{path}.{index}.js"
                scripts_by_path[path].append(script_path)
                tree_sitter_sources[script_path] = script
                expression_offsets[script_path] = offsets
            identifiers = []
        elif extension == ".py":
            identifiers = _python_identifiers(content, path)
        elif extension in (".json", ".toml"):
            identifiers = _config_identifiers(content, path)
        else:
            tree_sitter_sources[path] = content
            identifiers = []
        diagnostics.extend(_check_identifiers(path, identifiers, set(added_lines), dictionary))
    parsed_sources = _parse_tree_sitter_files(tree_sitter_sources, graphify_binary, expression_offsets)
    for changed_file in changed_files:
        path = changed_file["path"]
        for source_path in [path, *scripts_by_path.get(path, [])]:
            if source_path in parsed_sources:
                identifiers = [(item["line"], item["name"]) for item in parsed_sources[source_path]]
                diagnostics.extend(_check_identifiers(path, identifiers, set(changed_file["added_lines"]), dictionary))
    return list(dict.fromkeys(diagnostics))


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "parse-tree-sitter":
    raise SystemExit(_parse_tree_sitter_request())

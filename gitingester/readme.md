# GitIngest Processor CLI

This script provides a command-line interface (CLI) for processing directories using the `gitingest` library. It combines `.gitignore` patterns and user-specified include/exclude patterns to filter files and directories for ingestion.

## Features
- Parses `.gitignore` files to exclude specified patterns.
- Allows additional include/exclude patterns via CLI arguments.
- Processes directories with configurable maximum file size limits.
- Outputs results to a timestamped file in the `_processed` directory.

## Requirements
- Python 3.11+
- Install the `gitingest` library (poetry fails to resolve gh dependency correctly ATM):  
  ```bash
  pip install gitingest
  ```

## Usage

### Command-Line Arguments
| Argument   | Description                                 |
|------------|---------------------------------------------|
| `--dir`    | Directory to process (required).            |
| `--fs`     | Maximum file size in bytes (default: 20KB). |
| `--incl`   | Include patterns (semicolon-separated).     |
| `--excl`   | Exclude patterns (semicolon-separated).     |
| `--suffix` | Filename suffix (e.g. branch name etc)      |
| `--debug`  | Show debbugging info (excluded, included patterns) |

### Example
```bash
python3 main.py --dir /path/to/directory --incl "src*"
```
will read the lib code.
### Output
The script generates a timestamped output file in the `_processed` directory, e.g.:
- `directoryName_2025-03-28@23-08.txt` (no suffix)
- `directoryName_2025-03-28@23-08-yoursuffix.txt` (suffix provided)

## How It Works
1. Reads `.gitignore` from the specified directory and converts its patterns to exclusion rules.
2. Combines `.gitignore` exclusions with user-provided include/exclude patterns.
3. Processes files and directories using the `gitingest.ingest()` function.
4. Saves the results to a timestamped file with repo name prefix.

## Default Behavior
- If no `.gitignore` is found, the following default exclusion patterns are applied:
  ```python
  {"__pycache__*", "*venv*"}
  ```
- Lines in `.gitignore` containing `$`, `[`, `]` are ignored.

## Limitations & hints

- gitingest somehow has issues with broad patterns such as `*.py` etc. Scoping works better if we use --incl=`src*` for our packages,
`tests*` if needed, etc.


## Links

- https://gitingest.com/ (online hosted, can be used for open source repos etc)
- https://github.com/cyclotruc/gitingest

---

Feel free to modify this script or its parameters to suit your specific requirements!
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from envcontract import EnvContract, main


class EnvContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def test_detects_python_node_go_and_config_references(self):
        self.write("app.py", 'os.environ.get("APP_SECRET")\nos.getenv("APP_PORT")\n')
        self.write("web.ts", 'const endpoint = process.env.API_ENDPOINT;\n')
        self.write("main.go", 'port := os.Getenv("DB_PORT")\n')
        self.write("compose.yml", 'image: app:${IMAGE_TAG}\n')
        self.write(".env.example", "APP_SECRET=should-never-appear\nAPP_PORT=3000\n")
        report = EnvContract(self.root).audit()
        self.assertEqual(report.missing, ["API_ENDPOINT", "DB_PORT", "IMAGE_TAG"])
        self.assertEqual(report.unused, [])
        self.assertEqual(report.references["APP_SECRET"][0].path, "app.py")
        self.assertNotIn("should-never-appear", str(report.as_json()))

    def test_detects_duplicates_unused_and_shell_interpolation(self):
        self.write("run.sh", 'echo "$QUEUE_NAME"\necho "${REGION}"\n')
        self.write(".env.example", "QUEUE_NAME=\nQUEUE_NAME=again\nOLD_FLAG=yes\n")
        report = EnvContract(self.root).audit()
        self.assertEqual(report.missing, ["REGION"])
        self.assertEqual(report.unused, ["OLD_FLAG"])
        self.assertEqual(report.duplicate_declarations, ["QUEUE_NAME"])

    def test_never_reads_real_dotenv_and_ignores_build_trees(self):
        self.write(".env", "LIVE_KEY=actual-private-value\n")
        self.write("app.py", 'os.getenv("SAFE_KEY")\n')
        self.write("node_modules/pkg/index.js", 'process.env.PACKAGE_KEY\n')
        report = EnvContract(self.root).audit()
        self.assertEqual(report.used, ["SAFE_KEY"])
        self.assertNotIn("actual-private-value", str(report.as_json()))
        self.assertEqual(report.scanned_files, 1)

    def test_write_example_is_blank_and_refuses_overwrite(self):
        self.write("src/app.py", 'os.getenv("ZED")\nos.getenv("ALPHA")\n')
        output = EnvContract(self.root).write_example("config/.env.example")
        self.assertEqual(output.read_text(encoding="utf-8").splitlines()[1:], ["ALPHA=", "ZED="])
        with self.assertRaises(FileExistsError):
            EnvContract(self.root).write_example("config/.env.example")
        EnvContract(self.root).write_example("config/.env.example", force=True)

    def test_check_exit_code_and_json_output(self):
        self.write("app.py", 'process.env.MISSING\n')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main([str(self.root), "--check", "--format", "json"])
        self.assertEqual(code, 1)
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed["missing"], ["MISSING"])
        self.assertFalse(parsed["clean"])

    def test_key_location_deduplicates_same_line(self):
        self.write("app.js", 'use(process.env.PORT, process.env.PORT)\n')
        report = EnvContract(self.root).audit()
        self.assertEqual(len(report.references["PORT"]), 1)


if __name__ == "__main__":
    unittest.main()

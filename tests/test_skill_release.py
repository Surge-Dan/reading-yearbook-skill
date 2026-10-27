import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'reading-yearbook-skill/scripts'))
from skill_release import manifest,verify,check_resources,REQUIRED


class ReleaseTests(unittest.TestCase):
    def test_generated_book_sources_caches_and_private_state_never_ship(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'SKILL.md').write_text('public skill', 'utf-8')
            for folder in ('output/books', 'private', '.ebook-workbench/jobs/a', '.cache', '.history', '.diagnostics'):
                file = root / folder / 'private.txt'
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text('source book or runtime state', 'utf-8')
            self.assertEqual([item['path'] for item in manifest(root)['files']], ['SKILL.md'])

    def test_ebook_service_and_pinned_rules_are_required_install_resources(self):
        for missing in ('scripts/serve_ebook.py', 'scripts/ebook_verification.py', 'scripts/ebook_agent.py', 'scripts/ebook_agent_bridge.py', 'scripts/distillation_result.py', 'scripts/report_reader.py', 'assets/ebook-reader-section.html', 'third_party/cangjie/UPSTREAM.json'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in set(REQUIRED) | {missing}:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                (root / missing).unlink()
                with self.assertRaisesRegex(ValueError, '安装缺件'):
                    check_resources(root)

    def test_git_line_ending_conversion_does_not_break_text_manifest(self):
        with tempfile.TemporaryDirectory() as tmp,patch('skill_release.REQUIRED',[]):
            root=Path(tmp);source=root/'entry.py';source.write_bytes(b'print("hello")\n')
            expected=manifest(root);(root/'release-manifest.json').write_text(json.dumps(expected),encoding='utf-8')
            source.write_bytes(b'print("hello")\r\n')
            self.assertEqual(verify(root),expected)
            source.write_bytes(b'print("changed")\r\n')
            with self.assertRaisesRegex(ValueError,'版本不匹配'):verify(root)

    def test_vendored_text_template_hash_survives_windows_git_conversion(self):
        with tempfile.TemporaryDirectory() as tmp, patch('skill_release.REQUIRED', []):
            root = Path(tmp); source = root / 'DIGEST.md.template'
            source.write_bytes(b'# Digest\n\n{overview}\n')
            expected = manifest(root)
            (root / 'release-manifest.json').write_text(json.dumps(expected), 'utf-8')
            source.write_bytes(b'# Digest\r\n\r\n{overview}\r\n')
            self.assertEqual(verify(root)['version'], expected['version'])

    def test_svg_and_browser_scripts_survive_git_checkout_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp,patch('skill_release.REQUIRED',[]):
            root=Path(tmp)
            for name,content in [('shape.svg',b'<svg>\n</svg>\n'),('render.cjs',b'const x = 1;\n')]:
                (root/name).write_bytes(content)
            expected=manifest(root)
            (root/'release-manifest.json').write_text(json.dumps(expected),encoding='utf-8')
            for name in ('shape.svg','render.cjs'):
                source=root/name;source.write_bytes(source.read_bytes().replace(b'\n',b'\r\n'))
            self.assertEqual(verify(root),expected)

    def test_manifest_paths_cannot_read_outside_installation(self):
        with tempfile.TemporaryDirectory() as tmp,patch('skill_release.REQUIRED',[]):
            root=Path(tmp)
            (root/'release-manifest.json').write_text(json.dumps({'version':'test','files':[{'path':'../outside','sha256':'irrelevant'}]}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'路径无效'):verify(root)


if __name__=='__main__':unittest.main()

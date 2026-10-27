# 只读多书报告的受控回归

在仓库根目录运行，使用已有 Python、Node、Playwright 与 Edge／Chromium；Python 依赖见 Skill 的 requirements.txt。测试不安装运行时，不访问网络、不调用模型，也不读取私人书籍。

```powershell
python -X utf8 -m unittest discover -s tests -p test_report_reader_fixture.py -v
$env:PYTHON = 'D:/Python/python.exe' # 可省略，默认 python
node tests/report_reader_browser.cjs
```

需要时通过 `NODE_PATH` 指向已有 Playwright 包目录；`BROWSER_EXECUTABLE` 可指定浏览器，默认使用 Windows Edge 的标准安装路径。

浏览器测试默认调用已提交的 `tests/build_report_reader_fixture.py`，在系统临时目录生成两份受控 sample 包和报告。覆盖正文模式与公开试读模式、真实包校验、只读切书、来源范围与机械示例页脚、复制及 MD/HTML/PNG/ZIP、375px 和无 HTTP 请求。标题与预期内容从生成的包读取，不依赖忽略目录、固定书名或私人数据。样例不计入年度已读书目，不能当作真实模型效果评测。

也可单独重建测试报告：

```powershell
python -X utf8 tests/build_report_reader_fixture.py --output demo-output/reader-fixture/index.html
node tests/report_reader_browser.cjs demo-output/reader-fixture/index.html
```

传入其他报告时，必须是具有两份受控 sample 包和对应阅读视角／金句的测试报告。公开六本年鉴示例仍由 `reading-yearbook-skill/examples/build_html_demo.py` 重建，属于另一份展示材料。

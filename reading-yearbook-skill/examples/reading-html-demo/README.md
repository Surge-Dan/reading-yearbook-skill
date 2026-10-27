# 当前HTML阅读年鉴示例

`index.html`由当前`build_reading_html.py`生成，使用当前CSS、纸本插画和网页脚本。`images/`中的PNG通过这个网页的分享预览与实际导出按钮生成，不是独立deck工程的作品。

## 数据说明

`demo-data.json`包含6本虚构书籍，年份为2026，虚构材料范围截至2026-10-01。书名、作者、简介和摘录均非真实出版物内容。阅读汇总、每本书时长及月度时长相互对应；书籍覆盖有划线、只有个人笔记、二者都有和二者都没有的情况。

另有一份 `source_mode:sample` 的受控短篇结果，由 builder 的真实短文证据经 `make_bundle` 生成，明确标记“非真实出版物／非个人阅读记录”。它只演示底部只读精华、可选阅读视角与原文金句，不增加年度六本书的统计，不代表模型生成质量。示例包不能用于真实报告通过前置门。

`covers/`为程序排印的原创示意封面，注明虚构书目。真实用户任务会整理对应出版物的封面；不能用这些示意封面冒充真实书籍。

网页默认选中四张概览及六张书卡，共10页。这只是示例的页数，真实任务根据已载入书目动态计算。`share-overview.png`只展示四张概览和两张代表书卡，完整图片保留在`images/`。

当前 `index.html` 已同步只读精华与中性纸色；`web-preview.png` 是此前彩色纸本的历史截图，未作为本次只读功能验证。原年度分享绘制入口保持不变，已有年度PNG仍是历史导出样张。

## 重建

在Skill目录运行，使用现有Python及Pillow。Noto字体资源仅用于制作示意封面，不改变网页的系统字体回退策略。

```powershell
python -X utf8 examples/build_html_demo.py
```

使用已有Node、Playwright及Chromium或Edge导出示例截图与PNG；通过`NODE_PATH`指定已有Playwright目录，通过`BROWSER_EXECUTABLE`指定现有浏览器。不会自动安装浏览器。

```powershell
node examples/export_html_demo.cjs
```

运行后更新`web-preview.png`、`share-overview.png`、完整PNG及`preview-manifest.json`。该构建仅重建公开示例，不读取微信读书接口、密钥或私人阅读文件。

只读双书功能回归另用仓库已提交的 `tests/build_report_reader_fixture.py`；在仓库根目录运行 `node tests/report_reader_browser.cjs` 会自动生成受控测试页，无需 ignored helper 或预先存在的 demo-output。步骤和运行时路径配置见[回归说明](../../../tests/README-report-reader.md)。

## 验证与许可

导出脚本检查900×1200尺寸、网页预览与实际下载的像素差异、390px页面溢出、控制台错误和离线网络请求。Canvas复制与PNG编码可能在预乘透明边缘产生不超过一个色阶的舍入，报告保留实际最大差异，不要求编码字节相同。

字体优先本机Noto字族，其他设备回退系统中文字体，字形与断行可能不同。图表适配lieflat-charts，完整PolyFormNoncommercial1.0.0许可保留在HTML中。字体及纸本插画许可见对应assets目录；商用须满足所用素材的许可条件。

# 安装与首次使用

## 使用者先做

已有可用Agent时，直接让它读取本工作流并复用现有环境，不必另装Codex。下面的Codex步骤只是从零开始的参考入口；其他Agent先检查本地文件、命令执行和浏览器连接能力。

1. 打开 [OpenAI 官方快速开始](https://learn.chatgpt.com/docs/quickstart)，按 Desktop 安装入口获取 Windows 桌面端。
2. 使用自己的账号登录，选择 Codex，并打开本仓库所在的本地文件夹。不选云端任务。账号需具备实际访问资格。
3. 发送：“请读取 docs/setup.md，检查并准备当前工作流所需依赖。能自动完成的步骤直接完成，需要本人登录或系统确认时提示我。”
4. 告诉助手本次使用哪个浏览器；已有明确选择不需重复回答。确认工具能在同一会话完成制作及复核后，再在该浏览器登录秀米。

普通使用者无需手动编写以下命令。安装权限、登录和服务付费由本人处理，不向助手或维护者提供密码。

## AI 执行：安装依赖

1. 检查系统盘和缓存目录有可用空间；选择本地工作目录。不要自动删除用户文件，也不要覆盖其他环境。
2. 检查 Python 3.11+；缺少时从 [Python 官方 Windows 下载](https://www.python.org/downloads/windows/) 获取。确认实际可执行文件和版本。
3. 下载 [all-to-xiumi 固定源码 ZIP](https://github.com/hanselhan23/all-to-xiumi/archive/2f92030687a1ebb891e07b6f3747484456fc8bbb.zip)，解压到独立工具目录。上游为 [hanselhan23/all-to-xiumi](https://github.com/hanselhan23/all-to-xiumi)，不要以未经核验的同名包替代。
4. 该固定版本的 `pyproject.toml` 需要将构建后端 `setuptools.backends._legacy:_Backend` 精确改为 `setuptools.build_meta`；只在原值匹配时替换。
5. 用选定 Python 创建虚拟环境：`python -m venv .venv`，然后用该环境的 Python 执行 `-m pip install <源码目录>`。PDF 输入确有需要时另装 pdfplumber。
6. 执行虚拟环境中的 `all-to-xiumi --help`，确认安装。安装成功不等于秀米登录及编辑成功。

## AI 执行：保持同一个浏览器

使用 [同会话脚本](../wechat-editorial-workflow/scripts/same_session.py)，以持续的交互终端运行：

```text
<虚拟环境Python> -i <仓库>/wechat-editorial-workflow/scripts/same_session.py --browser <chrome或edge> --profile <本地专用资料目录> --cache <有空间的缓存目录>
```

将占位符替换为实际路径，带空格的路径正确引用。终端工具需保留标准输入（支持时使用 tty=true）。同一资料目录不能同时被两个浏览器进程占用，不复制用户资料或Cookie。
既有草稿加 `--resume <HTTPS秀米草稿链接>`。新稿启动后，当前进程提供 `driver` 及以下函数：

```python
url = import_new(driver, html_path, title)
before = reopen(driver)
snapshot(driver)
replace_paragraph(driver, old_text, new_text)
save(driver)
after = reopen(driver)
```

所有步骤复用该 `driver`，不跳转到助手内置浏览器。`import_new` 只用于新稿；续改先备份，不能重新整篇导入。替换函数只处理唯一的纯文本段落；媒体、链接及复杂内联格式通过同一会话的编辑界面处理。
`save` 等待保存状态完成；`reopen` 等待正文及加载遮罩恢复。仍需比较预期文字、未修改部分、图片及实际样式，不能只凭草稿URL判断完成。
同会话入口遵守宿主的工具和权限要求。如果宿主不允许此控制方式，登录前说明具体缺口，不绕过限制。

## 首次检查

用明确标注的虚构稿件确认：图片上传后复开仍可加载；标题、正文、图注样式有区分；局部修改后其他内容保持；保存复开仍可编辑。未通过时先定位错误，不反复创建新稿。

## 常见处理

- 驱动无法启动：检查浏览器、驱动下载、缓存和磁盘空间，区分原因。
- 登录阻断：在原浏览器由使用者登录，不要求另一浏览器重复登录。
- 保存超时：先检查页面和已有草稿，不立即刷新或重建。
- 连接断开：确认原进程状态，优先恢复；原实例已退出时用相同资料目录和草稿链接恢复，并明确记录恢复事实。
- 任务完成：保留浏览器供使用者检查。仅在确定结束会话时调用 `driver.quit()`。

## 学院固定规范

制作前读取 `wechat-editorial-workflow/references/fixed-layout.md`，使用compose_article生成正文、三张品牌图和三级栏位；保存后用audit_article结合内容清单核验。不能以同会话连接成功代替学院格式验收。

## 获取学院品牌素材

公开仓库不分发学院图片。确认自己有权用于学院账号后，让AI运行：

```text
<Python> wechat-editorial-workflow/scripts/fetch_brand_assets.py
```

脚本从清单记录的公开原始地址下载三张固定图片并核对哈希；不会读取账号或登录信息。来源失效或文件变化时停止，先向维护者确认，不随意换图。
素材下载不授予任何额外版权或商标许可，详见仓库的第三方权利说明。

## 一次执行与恢复

安装完成后，Agent可使用统一入口，避免为每一步另写脚本：

```text
<环境Python> -i wechat-editorial-workflow/scripts/run_article.py <材料.json> --work-dir <本篇任务目录> --browser <chrome或edge> --profile <本机资料目录> --cache <缓存目录>
```

任务目录保留源文件、独立计划、run.json主稿记录、审计与真实预览。再次运行同一任务只验证记录的主稿，不再创建；输入变化会要求按明确修改处理，不能无提示覆盖现有稿件。未知保存状态应先保留现场查明。
如需局部改文，在同一交互会话使用replace_paragraph并传入原plan，得到updated_plan；save后reopen，再对updated_plan审计。脚本有任务记录时自动备份修改前正文、元数据和计划；复杂富文本继续使用原生局部编辑方式。
统一入口的成功状态是layout_verified_visual_review_pending：布局检查通过、等待执行者查看真实成品，不代表用户已认可或审核通过。技术故障不需要用户选择实现方式，只有本人登录、权限和实际缺失资料等才交给用户。

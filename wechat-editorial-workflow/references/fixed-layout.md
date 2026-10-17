# 固定规范制作

## 生成

本入口适用于基础生成或定制HTML路线；不是所有排版任务的必经步骤。用户指定旧稿、秀米模板或互动组件时，先按 [风格与路线](design.md) 选择制作方法，不能用整篇导入覆盖原生组件。

使用 `scripts/compose_article.py` 按独立可编辑组件生成基础稿件和同名 `.plan.json` 内容顺序清单，自动检查随附品牌文件哈希，并安排固定首尾和三层署名。输入为UTF-8 JSON：

```json
{
  "title": "本篇标题",
  "letter_spacing": 0,
  "credits": {"编辑": "本篇编辑", "校对": "本篇校对", "审阅": "本篇审阅"},
  "blocks": [
    {"type": "heading", "text": "按内容决定是否需要标题"},
    {"type": "paragraph", "text": "正文内容"},
    {"type": "paragraph", "text": "另一段正文"},
    {"type": "image", "path": "本篇配图.jpg"},
    {"type": "caption", "text": "图片说明"}
  ]
}
```

命令：`<Python> scripts/compose_article.py <材料.json> <输出.html>`。相对配图路径按JSON所在目录解析。生成器采用CSS首行缩进，移除段首已有半角／全角空格，避免双重缩进。字距仅接受0或1。段间距按最终几何效果验收；生成器在组件层实现留白，避免一段编辑时重写全篇。标题和图注示例样式属于设计选择，不升级为正文硬规范。

内容结构、配色和章节数可以按文章设计，不强制使用全部block类型。复杂视觉稿也可以直接制作HTML，但必须同步生成覆盖全部段落、图片和署名的内容顺序清单，不能用模板效果覆盖文字要求。

## 导入与复核

按同会话入口导入生成的HTML。首次导入与保存复开分别检查，不新开浏览器。
读取 `.plan.json` 为plan，运行 `scripts/audit_article.py` 中的 `audit(driver, plan, expected_image_sources=None)`。秀米保存会移除自定义属性，因此按外部清单逐个对应实际p/img、原文及角色，不靠保存后的data属性，也不能仅凭字号猜测正文。
返回passed、errors及实际DOM证据；首次导入调用 `verify_uploaded_assets(result["image_sources"])`，逐个核对秀米CDN原图SHA-256与品牌清单一致，以证明上传的是正确原件；后续保存复开传入原image_sources核对图源未变。CDN重编码或读取失败时如实报告、人工核验，不自动降级成已通过。
有意修改正文时同步更新该篇清单后再验，不能为了消除错误盲目重建清单。audit只读取，不替用户审批。

检查涵盖：正文与内联文字字号／行高／字距、两端对齐、CSS或两个全角空格缩进、段间空行、左右留白、首尾顺序、三行人员与末图相邻、所有图加载。另需查看窄屏视觉效果；若存在复杂容器，检查完整祖先留白及实际内容边界，不能仅凭单个p样式通过。

工具报告成功不等于完整验收。内容清单缺失、正文或顺序不匹配、参数偏离、图片失效或三级缺项都必须修复。审阅结果、截图、个人稿件链接保留本地，不上传到分发仓库。

## 可选设计与正式状态

支持title/subtitle/heading、lead/callout、card、divider、image/caption和endnote；它们是可选设计块，不强制红色、星徽或三节结构。`theme`可设置accent、heading、text、muted、on_accent六位十六进制色值；card可指定badge及badge_width，路径按输入JSON目录解析。
正常正文仍用paragraph，lead和callout也接受同样的正文规范。需要显式空行时使用blank，禁止连续空行；相邻正文的总间隔只计一次，不能同时叠加30px段距和30px空段。
默认mode为final，三级人员必须齐全；试稿用mode=draft可以保留待确认，此时layout passed不代表人员已齐全或已审核。附加说明使用extra_credits，不增删编辑/校对/审阅三层。
验收返回passed、ready_for_review和warnings。passed只说明机器所覆盖的排版和内容一致性；实际审美、事实和审批仍单独检查。

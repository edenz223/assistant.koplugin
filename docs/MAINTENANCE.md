# 定制版维护说明

## 唯一开发入口

在 WSL 的 /home/edenz/codes/assistant.koplugin 开发。主线为 main。
origin 是 edenz223/assistant.koplugin；upstream 是 omer-faruq/assistant.koplugin。
Windows 源码副本仅供归档，不从那里提交或发布。跨系统复制先压缩。

## 日常修改

1. 在 main 执行 git pull --ff-only。
2. 修改一个功能，并补齐对应测试和必要说明。
3. 执行 ./test/run.sh 和 ./test/run_diagnose.sh。
4. 一个独立更改提交一次，再 git push origin main。

复杂功能可以使用 codex/<功能名> 短期分支，合入前整理成一个完整提交。
已发布提交不再重写；本次迁移的历史整理是一次性操作。
发布机器人可能推进 main，推送被拒绝时先获取并整合远端改动，不强推。

当前定制功能：
- 自定义提示词可带选中文本的句子上下文：utils/sentence_context.lua。
- 极简回复保留换行：dialogs/css.lua、dialogs/viewer.lua。

## 自动维护

GitHub Actions 的 Maintain and Release 工作流处理 main 推送、每天台湾时间
09:00 的上游同步，以及 Actions 页的 Run workflow。计划任务可能被 GitHub 延迟；
工作流被禁用或仓库长期不活跃时，需要在 Actions 页重新启用。

同步在 automation/candidate 临时分支执行 Git merge，保留上游提交历史。
冲突时停止，主线不变。通过以下检查后，才以普通快进推送更新 main 和版本标签：
- 官方最新 KOReader 稳定版的完整 Lua 测试。
- 固定 LuaLS 3.19.2 的静态诊断；CI 缺失诊断工具即失败。
- 两种 Markdown 渲染器的界面回归测试。
- 自动维护脚本的版本、打包、冲突、并发和重复运行测试。

同一流水线直接完成测试与发布，不依赖机器人推送触发另一条流水线。
不会自动运行翻译生成。上游修改定制代码或版本文件而发生冲突时，人工解决。

版本格式为 v年.月.日.序号，例如 v2026.10.29.1，日期取台湾时间。
版本准备单独提交。源码标签和 ZIP 中的 _meta.lua 版本相同。
正式 Release 只在附件上传成功后公开；上一次正式 Release 始终可用。
无新提交不重复发布。标签已推送但发布中断时，手动重跑继续同一版本。

仓库 Actions 需要启用，工作流需要 contents: write。
不需要额外 PAT。若以后启用分支保护，应让此发布流程具备更新主线的权限，
否则工作流会停止，不会绕过保护。

## 安装和更新

首次从自己的 GitHub Releases 下载 ZIP，解压到 KOReader 的 plugins 目录并重启。
随后使用插件内更新，默认更新源为 edenz223/assistant.koplugin。

显式 update_check_url 和 ota_github_url 设置仍优先于默认值。
如果旧 configuration.lua 曾指定原作者仓库，请由用户自行改成自己的仓库或移除覆盖值；
开发工具不会读取或修改真实配置。配置示例包含两个正确地址。
首次安装如仍显示缓存的旧标签，请在 OTA 输入框填写自己的日期版本完整标签。

源码 OTA 和发布 ZIP 均排除真实 configuration.lua、apikeys.lua 及开发文件。
更新器沿用现有的用户配置保留逻辑。

## 失败处理和恢复

在 Actions 查看失败步骤，下载 maintenance-<run>-<attempt> artifact。
其中包括候选历史、Git bundle、冲突 diff、测试日志及发布状态。
构建环境安装失败也会阻止发布，不降低测试门槛。

冲突：在本地 main 合并 upstream/main，解决冲突，运行检查，提交后推送。
并发修改：重新运行工作流，它会基于最新 main 重新验证。
中途发布失败：重新运行工作流，恢复相同标签的草稿和附件上传。
阅读器回退：在 OTA 菜单指定已存在的旧日期标签，或手动安装旧 Release ZIP。
回退不会改动 GitHub 的 latest 指向；必要时暂停工作流，避免继续推送问题版本。

历史迁移备份在 /home/edenz/codes/assistant-backups/20261029-main-migration/：
before.bundle 保存迁移前全部引用，refs.txt 记录原分支和标签。
可用 git clone before.bundle <恢复目录> 创建独立恢复副本，不覆盖当前仓库。
旧发布标签没有改写；本地 backup/* 分支保留旧主线定位。

## 本地验证自动化

python3 -m unittest discover -s .github/tests -v
SDL_VIDEODRIVER=dummy ./test/runui.sh ui/markdown_render
SDL_VIDEODRIVER=dummy ./test/runui.sh ui/markdown_render_puremd

首次阅读器验收需要实际设备：安装、重启、句子上下文、换行、升级和旧版恢复。
桌面自动化测试不能代替实机验收。

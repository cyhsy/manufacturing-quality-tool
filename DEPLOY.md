# 部署到 Streamlit Community Cloud

本文件说明如何把本项目部署到 <https://share.streamlit.io>（公开访问）。
部署本身需要**你自己的两个账号**（GitHub + Streamlit），无法由脚本代为完成 ——
Streamlit Cloud 只从 GitHub 仓库部署，且新建应用走浏览器 OAuth 授权。

## 一、前置条件

| 条件 | 当前状态 |
| --- | --- |
| 入口文件 | `app.py`（仓库根目录） |
| 依赖清单 | `requirements.txt`（运行时依赖，已精简）；开发依赖在 `requirements-dev.txt` |
| 数据与知识库 | `data/*.csv`、`knowledge/**` 已随仓库提交，无需额外挂载 |
| 应用脚本验证 | 通过（`AppTest` 完整执行 `app.py`，两个 Tab 正常渲染、无异常） |
| GitHub 远程仓库 | **需要先创建并 push**（当前仓库仅本地） |

### 本地运行前提（重要）

应用脚本在**导入阶段**就需要 `openai` 与 `pydantic`
（`modules/llm_quality_analysis.py` 顶层导入，未做延迟加载）。首次运行前：

```bat
pip install -r requirements.txt
```

否则浏览器中会看到 `ModuleNotFoundError: No module named 'openai'`。

另外注意：`/_stcore/health` 返回 `ok` **只代表服务进程已启动，并不检查脚本是否报错**
（Streamlit 在浏览器连接后才执行脚本）。因此健康检查**不能**作为部署验证依据，
判断标准应是「浏览器页面正常渲染」或 `AppTest` 完整执行通过。

> 依赖精简说明：原 `requirements.txt` 含未使用的 `matplotlib`
> （全项目无 `import matplotlib`/`pyplot`，已核实）与开发依赖 `pytest`/`ruff`，
> 现拆分为运行时 `requirements.txt` + 开发 `requirements-dev.txt`，以加快云端构建。
> `kaleido` 保留：Word 报告的图表转 PNG 依赖它（缺失时会降级为无图报告，不会报错）。


## 二、部署步骤

### 1. 创建 GitHub 仓库并推送

```bat
cd C:\Users\Administrator\Documents\deepseek-harness\default-workspace\manufacturing-quality-tool

:: 在 GitHub 上新建空仓库后（不要勾选 README/.gitignore），执行：
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git branch -M main
git push -u origin main
```

推送前确认仓库内**不含**敏感信息：`.gitignore` 已排除 `.venv/`、`__pycache__/`、
`.pytest_cache/`、`.ruff_cache/`、`.env`；`.streamlit/secrets.toml` 也不应提交
（密钥请在 Streamlit Cloud 后台填）。

### 2. 在 Streamlit Cloud 新建应用

1. 打开 <https://share.streamlit.io> → 用 GitHub 账号登录并授权；
2. 点 **Create app** → **Deploy a public app from GitHub**；
3. 填写：
   - Repository：`<你的用户名>/<仓库名>`
   - Branch：`main`
   - **Main file path：`app.py`**
   - App URL（子域）：见下方「子域注意事项」
4. 点 **Deploy**，等待构建（首次约 3–6 分钟，`kaleido` 体积较大）。

### 3. 配置密钥（可选，用于启用 LLM 功能）

在应用页面 → **Settings → Secrets**，填入：

```toml
DEEPSEEK_API_KEY = "sk-xxxxxxxxxxxxxxxx"
```

应用启动时会自动把该 Secret 桥接到环境变量（`app.py` 中的 `_bridge_streamlit_secrets()`），
因此 agents/ 与 modules/ 里既有的 `os.environ` 读取路径在云端同样生效。

**不配置也不会报错**：LLM 功能自动回退到规则模式
（Supervisor 会标注「LLM 规划未采纳（未配置 DEEPSEEK_API_KEY …）」）。

## 三、子域注意事项（重要）

Streamlit Cloud 的子域在**全平台唯一**，先到先得。

实测结论（2026-10-11）：

| 子域 | `/` | `/_stcore/health` | 结论 |
| --- | --- | --- | --- |
| `manufacturing-quality-tool` | 200 | 200 `ok` | **已被占用**（已有应用在运行） |
| `zzz-nonexistent-control-9f3a2b` | 404 | 404 | 不存在的子域返回 404（对照组） |

因此 `https://manufacturing-quality-tool.streamlit.app/` **目前不属于本项目**：

- 若该应用**是你自己的**：进入该应用的 Settings 把 Repository/Branch/Main file path
  改成上面的仓库即可，URL 保持不变；
- 若**不是你的**：需要换一个未被占用的子域，例如
  `manufacturing-quality-tool-agent`、`mq-tool-<你的用户名>` 等。
  子域可在创建应用时指定，也可创建后在 Settings 中修改（会改变 URL）。

## 四、云端运行注意事项

| 事项 | 说明 |
| --- | --- |
| 文件系统是临时的 | 容器重启/重新部署会重置。`create_work_order(persist=True)` 写入的 `data/work_orders.csv` **不会长期保留**；驾驶舱与 Agent 默认只做只读分析（`persist=False`），不受影响 |
| Word 报告中的图表 | 依赖 `kaleido` 把 Plotly 图转 PNG；若云端该依赖不可用，`_fig_to_image()` 会捕获异常并降级为「无图 Word 报告」，不会报错 |
| 数据规模小 | `data/` 约 1.4 MB（13 个 CSV），内存与启动时间无压力 |
| 首次加载较慢 | 首次请求触发脚本执行与缓存预热，属正常现象 |
| 依赖版本 | `requirements.txt` 未锁定版本（沿用原项目风格）。若需可复现构建，建议后续固定到 `streamlit==1.57.*`、`pandas==3.0.*` 等已验证版本 |

## 五、每次更新代码后

```bat
git add -A
git commit -m "..."
git push
```

Streamlit Cloud 会自动重新部署（也可在应用页面点 **Reboot** 手动触发）。

## 六、本地等价验证

部署前建议先本地验证：

```bat
pip install -r requirements.txt
python -m streamlit run app.py
:: 或
run_app.bat
```

自动冒烟测试（不启动服务，直接执行应用脚本，会真实捕获脚本异常）：

```bat
python -m pytest tests/test_app_smoke.py -q
```

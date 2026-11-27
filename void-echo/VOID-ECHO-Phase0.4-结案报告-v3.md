# VOID ECHO · Phase 0.4 结案报告 v3
## 三个客户端、同一份 MCP 响应：谁能看见图片

> **取代** v1/v2。本轮全部数据来自服务端日志逐条导出，无转述、无筛选。
> **一句话结论：MCP 原生 image block 在 DSH 与 Codex 上稳定可用；在 ChatGPT 聊天端不可用。两跳机制不需要建。**

---

## 1. 最终判定表

| 客户端 | 接入方式 | 结果 | 依据 |
|---|---|---|---|
| **DSH Desktop 2.0.23-next** | Streamable HTTP 直连 `127.0.0.1:8765/mcp`（profile 热加载） | ✅ **稳定可用** | 多次实测：正确数出 tick 数量、sha256 与本地字节一致 |
| **Codex CLI 0.171.0-alpha.13.2** | `codex mcp add --url http://127.0.0.1:8765/mcp`（**不经隧道**） | ✅ **4/4 轮全对** | 见第 2 节 |
| **ChatGPT 聊天端** | Secure MCP Tunnel + Code Mode | ❌ **12 次尝试仅 2 次内容可见** | 见第 3 节 |

**架构结论：Phase 1 采用单通道（MCP 直接返回 `type: "image"`）。OpenAI 生态的接入载体从「ChatGPT 连接器」改为「Codex」。**

---

## 2. Codex 实测（决定性证据）

判据：`frame(n=1, secret=-1)` 时，服务端**当场随机抽取**「数量 1–3 × 颜色 6 × 斜线方向 3」= **54 种组合**，三个值**只写入本机日志**，任何 text block 都不提及；同时把 `run=<8位hex>` 放进文本块用于绑定。

| 轮 | 时刻 | run ID | 真值（日志） | Codex 回答 | 判定 |
|---|---|---|---|---|---|
| 1 | 16:13:56 | `71279ef9` | pink / 1 / horizontal | `71279ef9` pink / 1 / horizontal | ✅ 4/4 |
| 2 | 16:15:04 | `8b4da56d` | purple / 3 / backslash | `8b4da56d` purple / 3 / backslash | ✅ 4/4 |
| 3 | 16:15:50 | `070c2d83` | lime / 3 / backslash | `070c2d83` lime / 3 / backslash | ✅ 4/4 |
| 4 | 16:16:40 | `42ce0a9f` | teal / 2 / backslash | `42ce0a9f` 青绿 / 2 / 反斜线 | ✅ 4/4 |

**统计**：单轮四项全对的纯猜概率 `1/54`；四轮全对 `(1/54)⁴ ≈ 1.2×10⁻⁷`。run ID 四次逐字命中（每次约 43 亿分之一），**答案与调用一一对应，不存在串样或复用**。

**路径自述**（第 4 轮）：
> 「我直接看到了工具返回的图像，没有用代码解码 base64 或分析字节。」

**机制佐证**：Codex 二进制中存在 `failed to prepare tool output image` 这条错误路径，说明它**内置「把工具输出的图片准备成模型图像输入」的环节**——与实测结果一致。

**运行配置**（重要）：
- Codex 的 MCP 工具默认需要审批，`exec` 模式审批策略为 `never` → 首次调用被拦：`MCP tool call requires approval, but approval policy is never`。**Codex 没有猜测，直接报告被拦。**
- 放行方式：`default_tools_approval_mode` 取值 **`auto` / `prompt` / `writes` / `approve`**，本次用 `-c` 临时覆盖为 `approve`，**未写入配置文件**。
- 每轮消耗 8k–21k token，走 ChatGPT 订阅额度，**无 API 充值**。

---

## 3. ChatGPT 聊天端为什么判负

12 次尝试的完整分布：

| 结果 | 次数 | 备注 |
|---|---|---|
| ✅ 读到文本（run ID `033fca8c` 逐字抄回） | 1 | 15:56:56 |
| ✅ 感知到图像（**版本指纹陷阱通过**） | 1 | 15:05 A 轮 |
| ❌ 声称没有图像 / 没有可识别内容块 | 9 | |
| ❌ 连文本都没拿到 | 2 | 16:03、16:07 |

**内容可见率 ≈ 17%（2/12）。**

**故障定位**：不是隧道（`dispatcher completed` 正常递增、`failures` 恒为 2 且均为无关的 `harpoon` 通道）、不是服务端（原始 `content` 为 `list[text, text, image]`，`type` 齐全、base64 规范、PNG 魔数正确）、不是渲染器（54 组逐像素校准全对）。**是 Code Mode 把 MCP 结果绑进运行时时丢失内容块类型**——表现为 `{"type":"unknown","keys":["0"]}` 或空对象 `{}`，甚至什么都不暴露。

**v4 假设被推翻**：我曾据「15:56 抄对 run ID」推断「text 块 100% 送达」，因此设计了 base64-in-text 方案。后续两轮连 text 都没送达，**一次成功被我当成了结构性保证**。教训：**n=1 的样本不能支撑「可靠」二字。**

**A 轮那次「9 根」的定位**：版本指纹（旧渲染器无斜线面板）通过、结构描述与真实响应一致、她主动放弃可提供 sha256 的机会——**不是编造**。但 12 次里只成 1 次，**不能当依赖**。

---

## 4. 本轮踩到并已修复的自身缺陷（诚实记录）

| 缺陷 | 现象 | 根因 | 状态 |
|---|---|---|---|
| 渲染 off-by-one | 所有条数 +1，导致 A 轮一度被我判成「运气」 | 右侧 14px 边距内 `rel` 变负、`slot=-1`，`elif` 画出幽灵条 | ✅ 已修 + 54 组逐像素校准 |
| `elif` 分支永不可达 | 青刻度根本没画出来（字节与 secret=0 完全相同） | 左条分支条件已覆盖右半区 | ✅ 改为独立 `if` |
| `_sha256` 只接受 str | 传 bytes 时 `AttributeError`，工具静默 `is_error` | 函数按字符串写、按字节调 | ✅ 已修 |
| 判卷口径 4 次误判 | 额度、上下文、A 轮、v4 假设 | 单点证据推成普遍结论 | ✅ 改为**预注册判据 + 先校准量具** |

---

## 5. Phase 1 契约（可直接开发）

1. **图片一律用 MCP 原生 `type: "image"` content block**，PNG/JPEG/WebP/GIF，规范 RFC4648 base64。
2. **单响应自限幅**：目标 ≤ 64 KB，硬上限 1 MiB（Python SDK 客户端实测硬拒线）；文本类分页 ≤ 16 KB + `next_cursor`；长内容用 `result_id` 续取。**不依赖任何客户端截断。**
3. **接入载体**：DSH + Codex。**不承诺 ChatGPT 聊天内连接器**；若将来必须支持，走 Responses API 由我们自己编排。
4. **工具 schema 是契约**：两端都缓存工具定义，改参数必须触发客户端重新发现（DSH 靠 bump 配置，Codex 重启会话）。
5. **写操作不注册为工具**（DSH 无逐工具白名单）。
6. **凭据不进模型**：Cookie 只留在服务端进程；DSH 侧用 `${credential:REF}`。
7. **失败必须显式上报「未收到图片」**，禁止静默猜测——本轮三个客户端都做到了，产品要保住这个行为。

---

## 6. 本机状态与回滚点

| 项 | 状态 | 回滚 |
|---|---|---|
| Echo Server | 运行中 `127.0.0.1:8765` | `pkill -f void_echo_test.server` |
| tunnel daemon | 运行中 `127.0.0.1:8080` | 停后台任务 |
| DSH `void_echo_test` 条目 | **仍启用** | 还原 `cordis.patch.yml.bak-void-echo-20261127-121745` |
| Codex `mcp_servers.void_echo_test` | 已注册（审批未持久化） | `codex mcp remove void_echo_test`；配置备份 `config.toml.bak-void-echo-20261127-161049` |
| 真值日志 | `out/secrets.log` 16 行 | 不入库（已被 .gitignore 排除） |

*所有 `[实测]` 数字可复现：`verify_pixels.py`（54 组校准）、`selftest_client.py`（14 项回归）、`out/secrets.log`（逐次真值）。*

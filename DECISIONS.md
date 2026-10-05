# Decisions — bili-upstream

> Architecture Decision Record (ADR-lite). Freezes decisions with context,
> alternatives, and tradeoffs. No ceremony — just enough to answer "why did
> we do this?" six months later.
>
> Add new decisions at the top. Mark superseded decisions with a status update
> and a pointer to the replacement. Never delete old entries.

---

## Template

```
## YYYY-MM-DD — <Decision title>

**Status:** Proposed | Accepted | Deprecated | Superseded by <link>

**Context:** What drove this decision? What was the situation, constraint, or
problem that required a choice?

**Decision:** What did we choose? Be specific — name the technology, pattern, or
approach.

**Alternatives considered:**
- **Alternative A:** <Why we rejected it>
- **Alternative B:** <Why we rejected it>

**Tradeoffs:**
- **Gain:** <What this decision gives us>
- **Cost/Risk:** <What this decision costs us or risks>
```

---

## 2026-10-05-1 — 全量同步完整性校验：漂移容忍度 = max(3, total_reported 的 1%)

**Status:** Accepted

**Context:** 核心验收条件是"page.count=500 但只拿到 430 → 不能算全量同步成功"（用户明确强调，除非能证明剩余内容在抓取期间被删除）。但反过来"任何短缺都失败"也会误伤：全量拉取一个大 UP 主要花 1~2 分钟，期间视频可能被删除或新发布；且无法自证短缺原因。需要一个既能放过"合理漂移"、又让 500→430（drift 70）必然失败的判定规则。

**Decision:** `drift = total_reported - total_unique`。规则：① drift < 0（抓取期间新增投稿）→ 成功；② `0 <= drift <= max(3, total_reported × 1%)` → 成功 + log warn（manifest 同时保留两个数字供人工核对）；③ drift > 容忍度 → 抛 `BiliError("incomplete")`，/collect 返回 502，且**不落盘**（旧 snapshot 原样保留）。容忍度是 count 的纯函数，不加配置项。

**Alternatives considered:**
- **严格模式（短缺即失败）：** 最贴近"不能把 430 当成功"，但抓取期间删一个视频就整次同步失败，大 UP 主（1000+ 条、拉取更久）误伤概率不可忽略
- **宽容模式（短缺仅告警）：** 直接违背用户验收条件（430/500 必须失败）
- **固定容忍度（如恒 5 条）：** 对 count=10 的小 UP 主 5 条 = 缺 50%，过松；对 count=5000 又过严；"比例 + 下限"两头都稳

**Tradeoffs:**
- **Gain:** 小 UP 主接近严格（count=523 → 容忍 5，缺 6 条即失败）；大 UP 主有 1% 余量；500→430 场景必然失败（70 > 5）；零新增配置面
- **Cost/Risk:** "UP 主抓取期间删视频"与"抓取异常"在容忍度内不可区分 —— manifest 双数字 + log warn 留痕，可人工核对；若日后用户想调容忍度，再升为配置项并 supersede 本条

# Qwen 绘本生成项目（DashScope）

输入一段故事，先生成可审核分镜与参考图，再确认后出图。  
项目同时提供 CLI 和 Web 两种使用方式。

## 1. 环境准备

1. Python 3.10+
2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 配置环境变量：

```bash
copy .env.example .env
```

编辑 `.env`，填入：

- `DASHSCOPE_API_KEY`
- 可选：`TEXT_MODEL`（默认 `qwen-plus`）
- 可选：`JUDGE_MODEL`（默认 `qwen-max`）
- 可选：`IMAGE_MODEL`（默认 `qwen-image`）

## 2. 启动 Web

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

浏览器打开：`http://127.0.0.1:8000`

## 3. 使用 CLI

```bash
python -m app.cli --story-text "从前有一个住在沙漠边缘的小男孩..."
```

或：

```bash
python -m app.cli --story-file story.txt
```

## 4. Web 工作流（两阶段）

1. 选择参考图模式：
   - `上传参考图`：上传后用于一致性生成
   - `文字生成3张人物参考图`：系统先生成3张候选图，后续可选择其中1张
2. 提交预览：系统先生成 `1~10` 条分镜草案（数量由模型判断）
3. 在前端编辑分镜文本并审核通过
4. 选择参考图后开始生图
   - 涉及人物的分镜：强制走 `qwen-image-edit-max` + 参考图
   - 不涉及人物分镜：走 `qwen-image`

## 5. 输出目录

每次任务会在 `outputs/<task_id>/` 生成：

- `story.json`
- `storyboards.json`
- `reference_candidates.json`
- `prompts.json`
- `result.json`
- `images/shot_01.png ...`

## 6. 一致性策略（混合）

1. 先生成角色参考图（reference）
2. 为每个分镜使用统一角色描述 + 风格圣经 + 强约束提示词
3. 在分镜差异化内容基础上保持固定画风与人物外观

## 7. 常见报错与原因

- `401/403`：`DASHSCOPE_API_KEY` 错误或未生效
- `429`：请求过快触发限流，稍后重试
- `502`：上游模型服务错误或网络波动（已内置重试）
- 生成成功但图片为空：模型返回中无 URL，需检查模型可用性与配额

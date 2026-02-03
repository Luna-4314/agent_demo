# Real Estate CRM Agent Demo

本 Demo 模拟 BizMic 在房地产行业中的核心业务自动化流程。

系统通过 AI 将语音或文本形式的客户沟通内容，自动转化为结构化 CRM 数据与可执行业务任务，并在后端自动完成任务执行与数据更新。

在本 Demo 中，Google Firestore 用于模拟真实地产公司的 CRM 数据库系统。

### 运行

运行本 Demo 仅需以下步骤：

1. 创建 `.env` 文件  
2. 在其中配置可访问模型 `claude-sonnet-4-5-20250929` 的 Anthropic API Key  
3. 运行：

```bash
python agent.py
```

### 流程图

<img width="4839" height="11080" alt="Agent Demo" src="https://github.com/user-attachments/assets/694d9742-4e8c-4eca-ac44-29aa6fba57b9" />



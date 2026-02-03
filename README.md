# Real Estate CRM Agent Demo

本 Demo 模拟 BizMic 在房地产行业中的核心业务逻辑： 
通过 AI 自动将语音或文本形式的客户沟通内容，转化为结构化 CRM 数据与可执行任务

---

## 一、Demo 整体流程

### 1. 启动程序

运行本地 CLI 程序，进入 AI Agent 交互界面。

---

### 2. 输入方式

用户可以选择两种输入模式：

- **语音输入（mic）**
  - 使用 Google Cloud Speech-to-Text API 将实时录音转写为文本 transcript

- **文本输入（text）**
  - 直接粘贴通话内容或记录文本

两种方式最终都会统一转化为 transcript，进入后续 AI 解析流程。

---

### 3. Claude 解析信息与生成任务

Claude 作为 Real Estate Sales Team Assistant，对 transcript 进行理解与结构化处理，主要完成两类工作：

#### （1）抽取关键事实数据（Facts）

包括：

- 客户信息（Contact）
- 通话记录（Call Note）

#### （2）推理下一步应执行的业务动作（Intent / Actions）

在当前 Demo 中，Claude 主要支持并稳定处理以下三种任务类型：

##### a. Follow Up（跟进任务）

当语料中：

- 提供了较完整的客户联系方式（如 name + phone/email）
- 或关键信息不完整需要补充（如缺预算、缺联系方式）

Claude 会推理生成：

- `create_contact`（若满足创建条件）
- `create_task`，task_type = `follow_up`

用于后续经纪人继续跟进客户。

---

##### b. Schedule Tour（安排看房）

当语料中明确提到：

- 希望预约看房
- 或给出了具体看房时间（如 next week, tomorrow 等）

Claude 会推理生成：

- `create_task`，task_type = `schedule_tour`

---

##### c. Send Listings（发送房源信息）

当语料中明确表达：

- 希望收到房源推荐
- 请求查看可选房源

Claude 会推理生成：

- `create_task`，task_type = `send_listings`

---

##### d. Call Note（通话记录）

对于每一条输入语料，Claude 都会生成：

- `create_call_note` 动作  
- 并将原始 transcript 与 AI summary 存入数据库

用于 CRM 中的沟通历史记录。

---

##### 语料来源说明

输入语料既可以来自：

- 客户视角的通话内容  
- 也可以来自地产经纪人的内部记录或总结  

---

### 4. 自动更新 Firestore（模拟 CRM 数据库）

Claude 生成的事实数据与动作将自动写入 Google Firestore，模拟真实地产公司的 CRM 系统。

---

## 二、Firestore 数据结构设计

Demo 中包含三个核心 collections：

### 1. contacts

用于存储客户基础信息。

字段示例：

| Field | Type | Required |
|------|------|---------|
| name | string | required |
| email | string | optional |
| phone | string | optional |
| need | string | optional |
| budget | number | optional |
| timeline | string | optional |

创建条件原则：

- 只要包含 **name + (phone 或 email)** 即可创建 contact  
- 若缺失关键联系方式，则不创建 contact，而生成 follow up 任务

---

### 2. tasks

用于存储 AI 推理生成的业务任务。

字段示例：

| Field | Type | Required |
|------|------|---------|
| task_type | string | required |
| description | string | required |
| due | string or null | optional |
| contact_id | string or null | optional |

当前支持的 task_type：

- follow_up  
- schedule_tour  
- send_listings  

---

### 3. call_notes

用于存储沟通记录。

字段示例：

| Field | Type | Required |
|------|------|---------|
| summary | string | required |
| rawTranscript | string | required |
| contact_id | string or null | optional |

---

## 三、Prompt 设计核心原则

### 1. 明确角色设定

Claude 被设定为：

> Real Estate Sales Team Assistant

模拟地产经纪团队中的智能业务助理，负责理解客户沟通并推动业务流程。

---

### 2. 强制结构化信息抽取

Claude 需要同时完成：

- 抽取 CRM 事实数据（contact + call_note）
- 推理业务动作（tasks）

---

### 3. 输出必须为严格 JSON 字符串

要求：

- 只能输出 JSON
- 不允许 markdown
- 不允许 comments 或 explanations

原因：

该输出直接供程序解析与执行，必须保证机器可读性与结构化稳定性。

---

### 4. Facts 与 Intent 解耦设计

Claude 的输出分为两大层级：

#### Top-Level（Facts）

用于存储：

- contact 数据
- call_note 数据  

代表从语料中抽取出的“客观事实状态”。

#### Actions（Intent）

用于存储：

- Claude 推理出的“下一步该执行的业务操作”

代表系统需要执行的命令。

---

这种设计带来的优势：

- 可审计性：区分事实是否抽取正确 vs 动作是否合理  
- 可扩展性：后续可独立优化数据抽取或决策逻辑  
- 安全边界：动作层受更严格约束，避免不可控副作用  

---

### 5. Payload 设计与解耦原则

所有 actions 统一采用：

```json
{ "type": "...", "payload": {} }

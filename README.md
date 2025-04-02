# ChargptChat 插件

## 简介

ChargptChat 是一个基于 chargpt.ai API 的微信机器人聊天插件，支持多种 AI 模型，提供文本对话和图片生成功能。

## 功能特点

- 🤖 支持多种顶级 AI 大模型（OpenAI、Anthropic、Google 等）
- 🖼️ 支持 AI 图片生成，可指定比例和保存图片
- 🔄 流式响应，实时展示生成过程
- 🔒 内置敏感词过滤系统
- 🔧 高度可定制的配置选项
- 💬 仅通过触发词唤醒，不响应@消息

## 安装方法

1. 将插件文件夹复制到机器人的 `plugins` 目录下
2. 修改 `config.toml` 中的配置（尤其是 API 令牌）
3. 重启机器人

## 如何获取 API 令牌

本插件使用的是 DeepSider 的 API 令牌(authorization)，获取步骤如下：

1. 访问 [chargpt.ai](https://chargpt.ai) 网站
2. 注册并登录您的账号
3. 使用浏览器开发者工具(F12)打开网络面板(Network)
4. 在网站上进行任意操作（如发送一条消息）
5. 在网络请求中找到任意 API 请求，查看请求头中的`authorization`字段
6. 复制`Bearer`后面的完整 token 字符串
7. 将此 token 粘贴到`config.toml`文件的`api_token`字段

提示：API 令牌通常以`eyJ`开头，是一个较长的字符串。请确保复制完整的令牌，包括所有字符。

## 配置说明

配置文件位于 `plugins/ChargptChat/config.toml`，主要配置项包括：

### 基本配置

```toml
[basic]
enable = true                # 是否启用插件
trigger_keyword = "chat"     # 触发关键词
respond_to_at = false        # 是否响应@消息（默认关闭）
allow_private_chat = true    # 是否允许私聊使用
```

### API 配置

```toml
[api]
api_token = "your_token_here"  # 替换为你的 chargpt.ai API 令牌
base_url = "https://api.chargpt.ai"
client_version = "1.1.76"
language = "zh-CN"
```

### 模型配置

```toml
[model]
default_model = "openai/gpt-4o"  # 默认使用的AI模型
allow_model_selection = true     # 是否允许用户在消息中指定模型
```

### 图片生成配置

```toml
[image]
enable_image_generation = true            # 是否启用图片生成
default_image_model = "openai/gpt-4o-image"  # 默认图片生成模型
image_command = "画"                      # 图片生成命令前缀
default_ratio = "1:1"                    # 默认图片比例
save_images = true                       # 是否保存生成的图片
```

### 敏感词过滤

```toml
[filter]
enable_filter = true         # 是否启用敏感词过滤
replace_with = "***"         # 替换敏感词为指定字符
sensitive_words = [          # 敏感词列表
    "敏感词1",
    "敏感词2",
    "色情",
    "暴力"
]
```

## 使用方法

### 基本对话

- 发送 `chat 你好` 开始对话
- 插件仅响应以触发词开头的消息，不会响应@消息

### 图片生成

- 发送 `chat 画一只猫` 生成图片
- 指定比例：`chat 画16:9 城市夜景`（支持 1:1、16:9、9:16、4:3、3:4）

### 指定模型

- 在消息中临时指定模型：`chat [anthropic/claude-3.5-sonnet] 你好`
- 设置默认模型：`chat_model openai/gpt-4o`

## 命令列表

- `chat_help` - 查看完整帮助信息
- `chat_model` - 查看/设置默认 AI 模型
- `chat_image` - 查看/设置图片生成功能
- `chat_clear` - 清除当前会话历史
- `chat_quota` - 查询 API 使用配额

## 支持的模型

插件支持多种 AI 模型，包括：

### OpenAI 模型

- openai/gpt-4o - GPT-4o 模型
- openai/gpt-4o-mini - GPT-4o mini 模型
- openai/gpt-4o-image - 支持图像生成
- openai/o1 - o1 模型
- openai/o3-mini - o3 mini 模型

### Anthropic 模型

- anthropic/claude-3.5-sonnet - Claude 3.5 Sonnet
- anthropic/claude-3.7-sonnet - Claude 3.7 Sonnet

### Google 模型

- google/gemini-2.0-pro - Gemini 2.0 Pro
- google/gemini-2.0-flash - Gemini 2.0 Flash
- google/gemini-2.0-pro-exp-02-05 - Gemini 2.0 Pro 实验版

### DeepSeek 模型

- deepseek/deepseek-r1 - DeepSeek R1 671B
- deepseek/deepseek-chat - DeepSeek V3
- deepseek/deepseek-chat-v3-0324 - DeepSeek V3 0324 版

### X-AI 模型

- x-ai/grok-3 - Grok 3
- x-ai/grok-3-reasoner - Grok 3 Reasoner

### 通义千问模型

- qwen/qwq-32b - QwQ 32B
- qwen/qwen-max - Qwen Max

## 图片生成参数设置

```
chat_image                   # 查看当前设置
chat_image ratio 1:1         # 设置默认图片比例
chat_image enable true/false # 启用/禁用图片生成
chat_image save true/false   # 启用/禁用图片保存
chat_image model openai/gpt-4o-image # 设置默认图片生成模型
```

## 开发者信息

- 版本: 1.0.0
- 作者: ChatGPT
- 基于: chargpt.ai API

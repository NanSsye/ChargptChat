from loguru import logger
import tomllib
import os
import asyncio
import time
import re
from typing import Dict, List, Optional
import aiohttp

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase
from .api_client import ChargptAPIClient


class ChargptChat(PluginBase):
    description = "Chargpt.ai AI聊天插件"
    author = "ChatGPT"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        
        # 获取配置文件路径
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
                
            # 读取基本配置
            basic_config = config.get("basic", {})
            self.enable = basic_config.get("enable", False)
            self.trigger_keyword = basic_config.get("trigger_keyword", "ai")
            self.respond_to_at = basic_config.get("respond_to_at", True)
            self.allow_private_chat = basic_config.get("allow_private_chat", True)
            
            # 读取API配置
            api_config = config.get("api", {})
            self.api_token = api_config.get("api_token", "")
            self.base_url = api_config.get("base_url", "https://api.chargpt.ai")
            self.client_version = api_config.get("client_version", "1.1.76")
            self.language = api_config.get("language", "zh-CN")
            
            # 读取模型配置
            model_config = config.get("model", {})
            self.default_model = model_config.get("default_model", "openai/gpt-4o")
            self.allow_model_selection = model_config.get("allow_model_selection", False)
            self.prompt_template = model_config.get("prompt_template", "{message}")
            
            # 读取图片生成配置
            image_config = config.get("image", {})
            self.enable_image_generation = image_config.get("enable_image_generation", True)
            self.default_image_model = image_config.get("default_image_model", "openai/gpt-4o-image")
            self.image_command = image_config.get("image_command", "画")
            self.default_ratio = image_config.get("default_ratio", "1:1")
            self.image_save_path = image_config.get("image_save_path", "images")
            self.save_images = image_config.get("save_images", True)
            self.web_access = image_config.get("web_access", "close")
            self.timezone = image_config.get("timezone", "Asia/Shanghai")
            
            # 读取聊天配置
            chat_config = config.get("chat", {})
            self.max_history = chat_config.get("max_history", 10)
            self.separate_context = chat_config.get("separate_context", True)
            self.timeout = chat_config.get("timeout", 60)
            self.show_thinking = chat_config.get("show_thinking", True)
            
            # 初始化API客户端
            self.api_client = ChargptAPIClient(
                api_token=self.api_token,
                base_url=self.base_url,
                client_version=self.client_version,
                language=self.language,
                default_model=self.default_model,
                prompt_template=self.prompt_template
            )
            
            # 用于记录响应状态的字典
            self.responding_to = {}
            
            # 确保图片保存目录存在
            if self.save_images:
                image_dir = os.path.join(os.path.dirname(__file__), self.image_save_path)
                if not os.path.exists(image_dir):
                    try:
                        os.makedirs(image_dir)
                        logger.info(f"创建图片保存目录: {image_dir}")
                    except Exception as e:
                        logger.error(f"创建图片保存目录失败: {str(e)}")
                        self.save_images = False
            
        except Exception as e:
            logger.error(f"加载ChargptChat配置文件失败: {str(e)}")
            self.enable = False

    async def async_init(self):
        # 检查配额，确认API可用
        if self.enable and self.api_token:
            try:
                quota_result = await self.api_client.get_quota()
                if quota_result["success"]:
                    logger.info(f"ChargptChat API连接成功")
                else:
                    logger.warning(f"ChargptChat API配额检查失败: {quota_result.get('error', '未知错误')}")
            except Exception as e:
                logger.error(f"ChargptChat API初始化异常: {str(e)}")
                
    @on_text_message(priority=90)  # 设置非常高的优先级，确保最先执行
    async def detect_trigger_keyword(self, bot: WechatAPIClient, message: dict):
        """检测唤醒词并标记为处理中"""
        if not self.enable:
            return True
            
        # 兼容不同的消息结构
        content = message.get("content", message.get("Content", ""))
        
        # 检查是否包含触发词
        if content.lower().startswith(f"{self.trigger_keyword} ") or content.lower() == self.trigger_keyword:
            logger.info(f"ChargptChat检测到唤醒词: {content}，继续执行自己的处理函数")
            # 返回True以允许插件自己的后续处理函数执行
            return True
            
        # 不包含触发词，继续处理
        return True

    @on_text_message(priority=50)  # 设置更高优先级，确保在handle_text之前执行
    async def handle_blocking(self, bot: WechatAPIClient, message: dict):
        """处理敏感词阻塞"""
        if not self.enable:
            return True
            
        # 兼容不同的消息结构
        content = message.get("content", message.get("Content", ""))
        from_user_id = message.get("sender_id", message.get("SenderWxid", ""))
        room_id = message.get("room_id", message.get("FromWxid", ""))
        
        # 检查消息内容是否包含触发词
        if not content.lower().startswith(f"{self.trigger_keyword} ") and not content.lower() == self.trigger_keyword:
            return True
            
        # 移除触发关键词，提取实际查询内容
        query = content[len(self.trigger_keyword):].strip() if content.lower() != self.trigger_keyword else ""
        
        # 敏感词名单(可以根据需要修改或从配置文件读取)
        sensitive_words = ["敏感词1", "敏感词2", "违禁词", "色情", "暴力", "政治"]
        
        # 检查是否包含敏感词
        for word in sensitive_words:
            if word in query:
                logger.warning(f"检测到敏感词: {word}, 消息: {query}")
                await bot.send_at_message(room_id or from_user_id, 
                    f"抱歉，您的消息包含敏感内容 ({word})，已被拦截。请遵守社区规则和法律法规。", 
                    [from_user_id])
                return False  # 阻止后续处理
                
        # 不含敏感词，继续处理
        return True
        
    @on_at_message(priority=90)  # 设置非常高的优先级，确保最先执行
    async def detect_at_trigger(self, bot: WechatAPIClient, message: dict):
        """检测@消息"""
        # 如果设置了不响应@消息，直接返回True以继续执行其他插件处理
        if not self.enable or not self.respond_to_at:
            return True
            
        # 兼容不同的消息结构
        from_user_id = message.get("sender_id", message.get("SenderWxid", ""))
        room_id = message.get("room_id", message.get("FromWxid", ""))
        
        # 必须在群聊中
        if not room_id:
            return True
            
        # 检测到@消息，继续执行自己的处理
        logger.info(f"ChargptChat检测到@消息，继续执行自己的处理函数")
        return True

    @on_at_message(priority=70)
    async def handle_at(self, bot: WechatAPIClient, message: dict):
        """处理@消息"""
        if not self.enable or not self.respond_to_at:
            return True
            
        # 添加调试日志
        logger.debug(f"ChargptChat收到@消息: {message}")
            
        # 兼容不同的消息结构
        content = message.get("content", message.get("Content", "")).strip()
        from_user_id = message.get("sender_id", message.get("SenderWxid", ""))
        room_id = message.get("room_id", message.get("FromWxid", ""))
        
        # 必须在群聊中
        if not room_id:
            return True
            
        # 获取会话ID
        session_id = room_id if self.separate_context else from_user_id
        
        # 检查是否已经在响应中
        if session_id in self.responding_to and self.responding_to[session_id]:
            await bot.send_at_message(room_id, "我正在思考上一个问题，请稍候...", [from_user_id])
            return False  # 已经处理，阻止其他插件执行
            
        # 如果内容为空，发送提示
        if not content:
            await bot.send_at_message(room_id, "请问有什么可以帮助您的？", [from_user_id])
            return False  # 已经处理，阻止其他插件执行
            
        logger.info(f"ChargptChat处理@消息: {content}")
        
        # 标记为正在响应
        self.responding_to[session_id] = True
        
        try:
            # 如果开启思考提示，先发送思考中的消息
            thinking_message_id = None
            if self.show_thinking:
                try:
                    thinking_result = await bot.send_at_message(room_id, "思考中...", [from_user_id])
                    # 检查返回值类型并适当处理
                    if isinstance(thinking_result, tuple) and len(thinking_result) > 0:
                        thinking_message_id = thinking_result[0]  # 假设第一个元素是消息ID
                    elif isinstance(thinking_result, dict) and thinking_result.get("status") == "success":
                        thinking_message_id = thinking_result.get("data", {}).get("message_id")
                    logger.debug(f"思考消息ID: {thinking_message_id}, 返回值类型: {type(thinking_result)}")
                except Exception as e:
                    logger.warning(f"发送思考消息异常: {str(e)}")
            
            # 处理响应
            response_text = ""
            logger.debug(f"开始处理API流式响应...")
            chunk_count = 0
            async for chunk in self.api_client.chat(session_id, content, None):
                chunk_count += 1
                response_text += chunk
                if chunk_count % 10 == 0:  # 每收到10个块记录一次日志
                    logger.debug(f"已接收{chunk_count}个响应块，当前长度:{len(response_text)}")
            
            logger.info(f"API响应接收完成，总计{chunk_count}个块，总长度:{len(response_text)}")
            
            # 确保回复不为空
            if not response_text.strip():
                response_text = "抱歉，AI没有返回有效回复。"
                logger.warning("API返回了空响应")
            
            # 发送完整响应
            if thinking_message_id:
                # 如果有思考中消息，则撤回
                try:
                    # 根据API不同，可能需要不同的参数组合
                    logger.debug(f"尝试撤回消息ID: {thinking_message_id}")
                    
                    # 尝试不同的撤回方式
                    try:
                        # 方式1: 直接使用消息ID
                        await bot.revoke_message(thinking_message_id)
                    except Exception:
                        try:
                            # 方式2: 提供聊天ID和消息ID
                            await bot.revoke_message(room_id or from_user_id, thinking_message_id)
                        except Exception:
                            # 方式3: 忽略撤回
                            logger.warning(f"无法撤回思考消息，将直接发送回复")
                except Exception as e:
                    logger.warning(f"撤回思考消息失败: {str(e)}")
                
            # 发送最终回复
            logger.debug(f"发送最终回复，长度:{len(response_text)}")
            await bot.send_at_message(room_id, response_text, [from_user_id])
            return False
                
        except Exception as e:
            logger.error(f"处理AI回复异常: {str(e)}")
            await bot.send_at_message(room_id, f"处理您的请求时出错: {str(e)}", [from_user_id])
            return False
        finally:
            # 标记为响应完成
            self.responding_to[session_id] = False
            
    @on_text_message(priority=90)  # 设置非常高的优先级，确保最先执行
    async def detect_command_trigger(self, bot: WechatAPIClient, message: dict):
        """检测命令唤醒词"""
        if not self.enable:
            return True
            
        # 兼容不同的消息结构
        content = message.get("content", message.get("Content", ""))
        
        # 检查是否包含命令前缀
        if content.startswith(f"{self.trigger_keyword}_"):
            logger.info(f"ChargptChat检测到命令唤醒词: {content}，继续执行自己的处理函数")
            return True
            
        # 不包含命令前缀，继续处理
        return True

    @on_text_message(priority=70)  # 设置较高优先级，保证能在一般插件之前执行
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        """处理文本消息"""
        if not self.enable:
            return True
            
        # 添加调试日志，查看接收到的消息结构
        logger.debug(f"ChargptChat收到消息: {message}")
        
        # 兼容不同的消息结构
        content = message.get("content", message.get("Content", ""))
        from_user_id = message.get("sender_id", message.get("SenderWxid", ""))
        room_id = message.get("room_id", message.get("FromWxid", ""))
        
        # 打印触发词和消息内容
        logger.debug(f"ChargptChat触发词检查: 当前词='{self.trigger_keyword}', 消息内容='{content}'")
        
        # 检查是否是私聊消息且是否允许私聊
        if not room_id and not self.allow_private_chat:
            return True
            
        # 非触发条件，直接返回
        if not content.lower().startswith(f"{self.trigger_keyword} ") and not content.lower() == self.trigger_keyword:
            return True
            
        logger.info(f"ChargptChat处理消息: {content}")
        
        # 获取会话ID
        session_id = room_id if room_id and self.separate_context else from_user_id
        
        # 移除触发关键词，提取实际查询内容
        if content.lower() == self.trigger_keyword:
            # 如果只有触发词没有内容，发送帮助信息
            await bot.send_at_message(room_id or from_user_id, "我是ChargptAI助手，请在触发词后面输入您的问题。", [from_user_id])
            return False  # 已经处理完成，阻止其他插件执行
            
        query = content[len(self.trigger_keyword):].strip()
        if not query:
            await bot.send_at_message(room_id or from_user_id, "我是ChargptAI助手，请在触发词后面输入您的问题。", [from_user_id])
            return False
        
        # 检查是否是图片生成请求
        is_image_request = False
        if self.enable_image_generation and query.startswith(self.image_command):
            image_prompt = query[len(self.image_command):].strip()
            if image_prompt:
                is_image_request = True
                logger.info(f"检测到图片生成请求: {image_prompt}")
            
        # 提取模型信息（如果允许并且指定了）
        model_to_use = None
        if self.allow_model_selection and query.startswith("[") and "]" in query:
            model_end = query.find("]")
            model_name = query[1:model_end].strip()
            if model_name:
                model_to_use = model_name
                # 移除模型指定部分
                query = query[model_end+1:].strip()
                logger.info(f"用户指定使用模型: {model_to_use}")
                
                # 重新检查是否为图片生成请求
                if self.enable_image_generation and query.startswith(self.image_command):
                    image_prompt = query[len(self.image_command):].strip()
                    if image_prompt:
                        is_image_request = True
                        logger.info(f"检测到指定模型的图片生成请求: {image_prompt}")
            
        # 检查是否已经在响应中
        if session_id in self.responding_to and self.responding_to[session_id]:
            await bot.send_at_message(room_id or from_user_id, "我正在思考上一个问题，请稍候...", [from_user_id])
            return False
            
        # 标记为正在响应
        self.responding_to[session_id] = True
        
        try:
            # 如果开启思考提示，先发送思考中的消息
            thinking_message_id = None
            if self.show_thinking:
                try:
                    thinking_result = await bot.send_at_message(room_id or from_user_id, "思考中...", [from_user_id])
                    # 检查返回值类型并适当处理
                    if isinstance(thinking_result, tuple) and len(thinking_result) > 0:
                        thinking_message_id = thinking_result[0]  # 假设第一个元素是消息ID
                    elif isinstance(thinking_result, dict) and thinking_result.get("status") == "success":
                        thinking_message_id = thinking_result.get("data", {}).get("message_id")
                    logger.debug(f"思考消息ID: {thinking_message_id}, 返回值类型: {type(thinking_result)}")
                except Exception as e:
                    logger.warning(f"发送思考消息异常: {str(e)}")
            
            # 根据请求类型处理响应
            response_text = ""
            
            if is_image_request:
                # 处理图片生成请求
                image_prompt = query[len(self.image_command):].strip()
                
                # 检查是否指定了比例，如 "画 16:9 一个风景"
                ratio = self.default_ratio
                if " " in image_prompt:
                    first_part = image_prompt.split(" ")[0]
                    if ":" in first_part and len(first_part) <= 5:  # 简单判断是否是比例格式
                        ratio_parts = first_part.split(":")
                        if len(ratio_parts) == 2 and ratio_parts[0].isdigit() and ratio_parts[1].isdigit():
                            ratio = first_part
                            image_prompt = image_prompt[len(first_part):].strip()
                            logger.info(f"检测到指定比例: {ratio}, 调整后的提示词: {image_prompt}")
                
                logger.debug(f"开始处理图片生成请求，提示词: {image_prompt}, 比例: {ratio}")
                
                # 获取并发送进度更新
                progress_updates = []
                image_url = None
                
                async for chunk in self.api_client.generate_image(
                    session_id, 
                    image_prompt, 
                    model=model_to_use or self.default_image_model,
                    ratio=ratio,
                    web_access=self.web_access,
                    timezone=self.timezone
                ):
                    # 累积进度更新，但不直接发送每个小更新
                    if "进度" in chunk or "%" in chunk:
                        progress_updates.append(chunk)
                        # 每接收到3个进度更新，或进度达到100%，发送一次更新
                        if len(progress_updates) >= 3 or "100%" in chunk or "生成完成" in chunk:
                            update_text = "图片生成中...\n" + "\n".join(progress_updates[-3:])
                            # 尝试更新思考消息，如果不行则发送新消息
                            try:
                                if thinking_message_id:
                                    await bot.edit_message(room_id or from_user_id, thinking_message_id, update_text)
                                else:
                                    await bot.send_at_message(room_id or from_user_id, update_text, [from_user_id])
                            except Exception as e:
                                logger.warning(f"更新进度消息失败: {str(e)}")
                    
                    # 如果是图片URL，保存下来
                    elif "![" in chunk and "](http" in chunk:
                        response_text = chunk
                        # 提取图片URL
                        start_idx = chunk.find("](") + 2
                        end_idx = chunk.find(")", start_idx)
                        if start_idx > 1 and end_idx > start_idx:
                            image_url = chunk[start_idx:end_idx]
                            logger.info(f"图片生成完成，URL: {image_url}")
                    else:
                        response_text += chunk
                
                # 如果有图片URL，可以在这里下载保存到本地
                if image_url and self.save_images:
                    try:
                        image_dir = os.path.join(os.path.dirname(__file__), self.image_save_path)
                        filename = f"{int(time.time())}_{session_id[-8:]}.png"
                        filepath = os.path.join(image_dir, filename)
                        
                        async with aiohttp.ClientSession() as session:
                            async with session.get(image_url) as img_response:
                                if img_response.status == 200:
                                    with open(filepath, 'wb') as f:
                                        f.write(await img_response.read())
                                    logger.info(f"图片已保存到: {filepath}")
                    except Exception as e:
                        logger.error(f"保存图片失败: {str(e)}")
            else:
                # 处理普通文本请求
                logger.debug(f"开始处理API流式响应...")
                chunk_count = 0
                async for chunk in self.api_client.chat(session_id, query, model_to_use):
                    chunk_count += 1
                    response_text += chunk
                    if chunk_count % 10 == 0:  # 每收到10个块记录一次日志
                        logger.debug(f"已接收{chunk_count}个响应块，当前长度:{len(response_text)}")
                
                logger.info(f"API响应接收完成，总计{chunk_count}个块，总长度:{len(response_text)}")
            
            # 确保回复不为空
            if not response_text.strip():
                response_text = "抱歉，AI没有返回有效回复。"
                logger.warning("API返回了空响应")
            
            # 发送完整响应
            if thinking_message_id:
                # 如果有思考中消息，则撤回
                try:
                    # 根据API不同，可能需要不同的参数组合
                    logger.debug(f"尝试撤回消息ID: {thinking_message_id}")
                    
                    # 尝试不同的撤回方式
                    try:
                        # 方式1: 直接使用消息ID
                        await bot.revoke_message(thinking_message_id)
                    except Exception:
                        try:
                            # 方式2: 提供聊天ID和消息ID
                            await bot.revoke_message(room_id or from_user_id, thinking_message_id)
                        except Exception:
                            # 方式3: 忽略撤回
                            logger.warning(f"无法撤回思考消息，将直接发送回复")
                except Exception as e:
                    logger.warning(f"撤回思考消息失败: {str(e)}")
                
            # 发送最终回复
            logger.debug(f"发送最终回复，长度:{len(response_text)}")
            await bot.send_at_message(room_id or from_user_id, response_text, [from_user_id])
            return False
                
        except Exception as e:
            logger.error(f"处理AI回复异常: {str(e)}")
            await bot.send_at_message(room_id or from_user_id, f"处理您的请求时出错: {str(e)}", [from_user_id])
            return False
        finally:
            # 标记为响应完成
            self.responding_to[session_id] = False

    @on_text_message(priority=70)
    async def handle_command(self, bot: WechatAPIClient, message: dict):
        """处理插件命令"""
        if not self.enable:
            return True
            
        # 兼容不同的消息结构
        content = message.get("content", message.get("Content", ""))
        from_user_id = message.get("sender_id", message.get("SenderWxid", ""))
        room_id = message.get("room_id", message.get("FromWxid", ""))
        
        # 检查命令前缀
        if not content.startswith(f"{self.trigger_keyword}_"):
            return True
            
        logger.info(f"ChargptChat处理命令: {content}")
        
        # 解析命令
        parts = content.split(" ", 1)
        command = parts[0][len(f"{self.trigger_keyword}_"):].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        # 获取会话ID
        session_id = room_id if room_id and self.separate_context else from_user_id
        
        # 处理不同命令
        if command == "clear":
            # 清除对话历史
            self.api_client.clear_conversation(session_id)
            await bot.send_at_message(room_id or from_user_id, "已清除当前会话历史记录", [from_user_id])
            return False
            
        elif command == "model":
            # 处理模型相关命令
            if not args:
                # 显示当前模型信息
                model_text = f"当前使用的默认模型: {self.default_model}\n"
                model_text += f"是否允许消息内指定模型: {'是' if self.allow_model_selection else '否'}\n\n"
                model_text += "如需在消息中指定模型，请使用格式: chat [模型名] 问题\n"
                model_text += "例如: chat [openai/gpt-4o] 你好\n\n"
                model_text += "可用模型列表:\n"
                model_text += "OpenAI模型:\n"
                model_text += "- openai/gpt-4o - GPT-4o模型\n"
                model_text += "- openai/gpt-4o-mini - GPT-4o mini模型\n"
                model_text += "- openai/gpt-4o-image - GPT-4o支持图像分析\n"
                model_text += "- openai/o1 - o1模型\n"
                model_text += "- openai/o3-mini - o3 mini模型\n"
                model_text += "- openai/gpt-3.5-turbo - GPT-3.5 Turbo模型\n"
                model_text += "Anthropic模型:\n"
                model_text += "- anthropic/claude-3.5-sonnet - Claude 3.5 Sonnet\n"
                model_text += "- anthropic/claude-3.7-sonnet - Claude 3.7 Sonnet\n"
                model_text += "Google模型:\n"
                model_text += "- google/gemini-2.0-pro - Gemini 2.0 Pro\n"
                model_text += "- google/gemini-2.0-flash - Gemini 2.0 Flash\n"
                model_text += "- google/gemini-2.0-pro-exp-02-05 - Gemini 2.0 Pro实验版\n"
                model_text += "- google/gemini-2.0-flash-thinking-exp-1219 - Gemini 2.0 Flash思考版\n"
                model_text += "DeepSeek模型:\n"
                model_text += "- deepseek/deepseek-r1 - DeepSeek R1 671B\n"
                model_text += "- deepseek/deepseek-chat - DeepSeek V3\n"
                model_text += "- deepseek/deepseek-chat-v3-0324 - DeepSeek V3 0324版\n"
                model_text += "X-AI模型:\n"
                model_text += "- x-ai/grok-3 - Grok 3\n"
                model_text += "- x-ai/grok-3-reasoner - Grok 3 Reasoner\n"
                model_text += "通义千问模型:\n"
                model_text += "- qwen/qwq-32b - QwQ 32B\n"
                model_text += "- qwen/qwen-max - Qwen Max\n"
                
                await bot.send_at_message(room_id or from_user_id, model_text, [from_user_id])
            else:
                # 用户指定了新的默认模型
                new_model = args.strip()
                if "/" in new_model:  # 确保格式正确
                    self.default_model = new_model
                    self.api_client.set_default_model(new_model)
                    await bot.send_at_message(room_id or from_user_id, f"默认模型已设置为: {new_model}", [from_user_id])
                else:
                    await bot.send_at_message(room_id or from_user_id, "模型格式不正确，请使用格式: 提供商/模型名\n例如: openai/gpt-4o", [from_user_id])
            return False
            
        elif command == "quota":
            # 获取配额信息
            try:
                logger.info("正在请求配额信息...")
                quota_result = await self.api_client.get_quota()
                logger.debug(f"配额响应: {quota_result}")
                
                if quota_result["success"]:
                    quota_data = quota_result["data"]
                    # 记录原始数据
                    logger.debug(f"原始配额数据: {quota_data}")
                    
                    # 格式化配额信息展示
                    quota_text = "ChargptAI 配额信息:\n"
                    quota_text += f"可用余额: {quota_data.get('available', '未知')}\n"
                    quota_text += f"使用情况: {quota_data.get('used', '未知')}/{quota_data.get('total', '未知')}\n"
                    
                    # 添加更多信息，如果有的话
                    if 'models' in quota_data:
                        quota_text += "\n可用模型:\n"
                        for model in quota_data['models']:
                            quota_text += f"- {model}\n"
                    
                    # 添加全部字段，便于分析
                    quota_text += "\n所有数据字段:\n"
                    for key, value in quota_data.items():
                        if key not in ['available', 'used', 'total', 'models']:
                            quota_text += f"- {key}: {value}\n"
                    
                    await bot.send_at_message(room_id or from_user_id, quota_text, [from_user_id])
                else:
                    error_msg = f"获取配额信息失败: {quota_result.get('error', '未知错误')}"
                    logger.warning(error_msg)
                    await bot.send_at_message(room_id or from_user_id, error_msg, [from_user_id])
            except Exception as e:
                logger.error(f"获取配额异常: {str(e)}")
                await bot.send_at_message(room_id or from_user_id, f"获取配额时出错: {str(e)}", [from_user_id])
            return False
                
        elif command == "help":
            # 帮助信息
            help_text = f"""ChargptAI 助手使用指南:

1. 基本使用:
   - 发送 "{self.trigger_keyword} 问题" 进行提问
   - 注：本插件仅通过触发词唤醒，不响应@消息

2. 图片生成:
   - 发送 "{self.trigger_keyword} {self.image_command}[描述]" 生成图片
   - 例如: {self.trigger_keyword} {self.image_command}一个动漫风格的机甲战士
   - 指定比例: {self.trigger_keyword} {self.image_command}16:9 一个宽屏风景
   - 可用比例: 1:1(方形)、16:9(宽屏)、9:16(竖屏)、4:3、3:4
   - 支持使用 [{self.default_image_model}] 模型

3. 模型选择:
   - 默认使用: {self.default_model}
   - 在消息中临时指定模型: {self.trigger_keyword} [模型名] 问题
     例如: {self.trigger_keyword} [anthropic/claude-3.5-sonnet] 你好
   - 更改默认模型: {self.trigger_keyword}_model 模型名
     例如: {self.trigger_keyword}_model openai/gpt-4o

4. 可用模型:
   OpenAI模型:
   - openai/gpt-4o - GPT-4o模型
   - openai/gpt-4o-mini - GPT-4o mini模型
   - openai/gpt-4o-image - 支持图像生成
   - openai/o1 - o1模型
   - openai/o3-mini - o3 mini模型
   - openai/gpt-3.5-turbo - GPT-3.5模型
   
   Anthropic模型:
   - anthropic/claude-3.5-sonnet - Claude 3.5
   - anthropic/claude-3.7-sonnet - Claude 3.7
   
   Google模型:
   - google/gemini-2.0-pro - Gemini 2.0 Pro
   - google/gemini-2.0-flash - Gemini 2.0 Flash
   
   DeepSeek模型:
   - deepseek/deepseek-r1 - DeepSeek R1 671B
   - deepseek/deepseek-chat - DeepSeek V3
   
   X-AI模型:
   - x-ai/grok-3 - Grok 3
   
   通义千问模型:
   - qwen/qwq-32b - QwQ 32B
   - qwen/qwen-max - Qwen Max

5. 其他命令:
   - {self.trigger_keyword}_clear: 清除当前会话历史
   - {self.trigger_keyword}_quota: 查询API使用配额
   - {self.trigger_keyword}_model: 查看/设置默认模型
   - {self.trigger_keyword}_image: 查看/设置图片生成功能"""
            await bot.send_at_message(room_id or from_user_id, help_text, [from_user_id])
            return False
        elif command == "image":
            # 处理图片生成相关设置
            if not args:
                # 显示当前图片生成设置
                image_text = f"图片生成功能设置:\n"
                image_text += f"启用状态: {'已启用' if self.enable_image_generation else '已禁用'}\n"
                image_text += f"默认模型: {self.default_image_model}\n"
                image_text += f"生成命令前缀: {self.trigger_keyword} {self.image_command}...\n"
                image_text += f"默认图片比例: {self.default_ratio}\n"
                image_text += f"保存图片: {'是' if self.save_images else '否'}\n"
                image_text += f"图片保存路径: {self.image_save_path}\n\n"
                image_text += f"使用示例:\n"
                image_text += f"{self.trigger_keyword} {self.image_command}一个动漫风格的机甲战士\n"
                image_text += f"{self.trigger_keyword} {self.image_command}16:9 一个宽屏风景\n"
                
                await bot.send_at_message(room_id or from_user_id, image_text, [from_user_id])
            else:
                # 解析设置参数
                arg_parts = args.split(" ", 1)
                setting = arg_parts[0].lower()
                value = arg_parts[1] if len(arg_parts) > 1 else ""
                
                if setting == "ratio" and value:
                    # 设置默认图片比例
                    if value in ["1:1", "16:9", "9:16", "4:3", "3:4"]:
                        self.default_ratio = value
                        await bot.send_at_message(room_id or from_user_id, f"默认图片比例已设置为: {value}", [from_user_id])
                    else:
                        await bot.send_at_message(room_id or from_user_id, f"不支持的比例设置，可用选项: 1:1, 16:9, 9:16, 4:3, 3:4", [from_user_id])
                
                elif setting == "enable":
                    # 启用/禁用图片生成
                    if value.lower() in ["true", "yes", "1", "on"]:
                        self.enable_image_generation = True
                        await bot.send_at_message(room_id or from_user_id, "图片生成功能已启用", [from_user_id])
                    elif value.lower() in ["false", "no", "0", "off"]:
                        self.enable_image_generation = False
                        await bot.send_at_message(room_id or from_user_id, "图片生成功能已禁用", [from_user_id])
                    else:
                        await bot.send_at_message(room_id or from_user_id, f"无效的参数，请使用 true/false", [from_user_id])
                
                elif setting == "save":
                    # 是否保存图片
                    if value.lower() in ["true", "yes", "1", "on"]:
                        self.save_images = True
                        # 确保图片保存目录存在
                        image_dir = os.path.join(os.path.dirname(__file__), self.image_save_path)
                        if not os.path.exists(image_dir):
                            try:
                                os.makedirs(image_dir)
                                logger.info(f"创建图片保存目录: {image_dir}")
                            except Exception as e:
                                logger.error(f"创建图片保存目录失败: {str(e)}")
                                self.save_images = False
                                await bot.send_at_message(room_id or from_user_id, f"无法创建图片保存目录，图片保存功能已禁用: {str(e)}", [from_user_id])
                                return False
                        await bot.send_at_message(room_id or from_user_id, f"图片保存功能已启用，保存路径: {image_dir}", [from_user_id])
                    elif value.lower() in ["false", "no", "0", "off"]:
                        self.save_images = False
                        await bot.send_at_message(room_id or from_user_id, "图片保存功能已禁用", [from_user_id])
                    else:
                        await bot.send_at_message(room_id or from_user_id, f"无效的参数，请使用 true/false", [from_user_id])
                        
                elif setting == "model" and value:
                    # 设置默认图片生成模型
                    if "/" in value and "image" in value.lower():
                        self.default_image_model = value
                        await bot.send_at_message(room_id or from_user_id, f"默认图片生成模型已设置为: {value}", [from_user_id])
                    else:
                        await bot.send_at_message(room_id or from_user_id, f"无效的模型，请确保模型名包含提供商前缀和image关键词", [from_user_id])
                
                else:
                    # 显示使用帮助
                    help_text = "图片生成设置命令用法:\n"
                    help_text += f"{self.trigger_keyword}_image - 显示当前设置\n"
                    help_text += f"{self.trigger_keyword}_image ratio 1:1 - 设置默认图片比例\n"
                    help_text += f"{self.trigger_keyword}_image enable true/false - 启用/禁用图片生成\n"
                    help_text += f"{self.trigger_keyword}_image save true/false - 启用/禁用图片保存\n"
                    help_text += f"{self.trigger_keyword}_image model openai/gpt-4o-image - 设置默认图片生成模型"
                    await bot.send_at_message(room_id or from_user_id, help_text, [from_user_id])
            
            return False
        else:
            # 未知命令
            await bot.send_at_message(room_id or from_user_id, f"未知命令: {command}，发送 {self.trigger_keyword}_help 查看帮助", [from_user_id])
            return False 
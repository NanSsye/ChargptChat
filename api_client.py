import aiohttp
import asyncio
import json
import time
from loguru import logger
from typing import Dict, List, Optional, AsyncGenerator


class ChargptAPIClient:
    """Chargpt.ai API客户端，处理与API的通信"""
    
    def __init__(self, api_token: str, base_url: str, client_version: str, language: str,
                default_model: str = "openai/gpt-4o", prompt_template: str = "{message}"):
        """初始化API客户端
        
        Args:
            api_token: API授权令牌
            base_url: API基础URL
            client_version: 客户端版本号
            language: 语言设置
            default_model: 默认使用的模型
            prompt_template: 提示词模板
        """
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")  # 移除末尾斜杠
        self.client_version = client_version
        self.language = language
        self.default_model = default_model
        self.prompt_template = prompt_template
        
        # 会话存储，key为会话ID，value为历史消息
        self.conversations: Dict[str, List[Dict]] = {}
        
    async def get_quota(self) -> Dict:
        """获取用户配额信息
        
        Returns:
            Dict: 用户配额信息
        """
        url = f"{self.base_url}/api/quota/retrieve"
        
        headers = self._get_headers()
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"获取配额失败: {response.status} - {error_text}")
                    return {"success": False, "error": f"API错误: {response.status}"}
                
                try:
                    data = await response.json()
                    return {"success": True, "data": data}
                except Exception as e:
                    logger.error(f"解析配额响应失败: {str(e)}")
                    return {"success": False, "error": f"解析响应失败: {str(e)}"}
    
    async def chat(self, session_id: str, message: str, model: str = None) -> AsyncGenerator[str, None]:
        """发送消息并以流式方式接收响应
        
        Args:
            session_id: 会话ID，用于跟踪对话历史
            message: 用户消息
            model: 使用的模型，为空则使用默认模型
            
        Yields:
            str: 响应消息片段
        """
        url = f"{self.base_url}/api/v2/chat/conversation"
        
        # 如果未指定模型，使用默认模型
        model_to_use = model if model else self.default_model
        # 生成提示词
        prompt = self.prompt_template.format(message=message)
        
        # 准备简单的请求体，模拟网页请求
        payload = {
            "message": message,
            "conversation_id": session_id,
            "model": model_to_use,    # 使用指定的模型
            "prompt": prompt          # 使用模板生成的提示词
        }
        
        headers = self._get_headers()
        logger.debug(f"发送聊天请求，payload: {payload}")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, headers=headers, json=payload, timeout=60) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"聊天请求失败: {response.status} - {error_text}")
                        yield f"API错误: {response.status}"
                        return
                    
                    logger.debug(f"收到响应，content-type: {response.headers.get('content-type')}")
                    
                    # 读取SSE响应
                    buffer = ""
                    full_response = ""
                    line_count = 0
                    raw_lines = []  # 用于保存原始响应行
                    
                    async for line in response.content:
                        line_text = line.decode('utf-8')
                        line_count += 1
                        raw_lines.append(line_text)
                        
                        # 每10行打印一次原始数据以便调试
                        if line_count <= 5 or line_count % 20 == 0:
                            logger.debug(f"原始响应行 {line_count}: {line_text}")
                        
                        # 处理事件行
                        if line_text.startswith('event:'):
                            event_type = line_text[6:].strip()
                            logger.debug(f"检测到事件: {event_type}")
                            
                            # 如果是错误事件，准备获取后续数据行
                            if event_type == "error":
                                logger.warning("收到错误事件，等待错误详情...")
                                continue
                        
                        # 解析方式 1: data: 前缀
                        if line_text.startswith('data:'):
                            data = line_text[5:].strip()
                            
                            if data == "[DONE]":
                                logger.debug("收到[DONE]标记")
                                break
                                
                            try:
                                json_data = json.loads(data)
                                
                                # 检查是否是错误响应
                                if json_data.get('code') in [1000, 1001, 1002, 1003, 1004, 1005] and 'message' in json_data:
                                    error_msg = json_data.get('message', '未知错误')
                                    debug_info = json_data.get('debugInfo', '')
                                    error_text = f"API错误({json_data.get('code')}): {error_msg}"
                                    if debug_info:
                                        error_text += f"\n调试信息: {debug_info}"
                                    logger.error(error_text)
                                    yield error_text
                                    return
                                
                                # 解析方式 1a: 使用code和data字段
                                if json_data.get('code') == 202 and 'data' in json_data:
                                    data_obj = json_data['data']
                                    if data_obj.get('type') == 'chat' and 'content' in data_obj:
                                        content = data_obj['content']
                                        if content:
                                            logger.debug(f"提取的内容块: {content}")
                                            buffer += content
                                            full_response += content
                                            yield content
                                
                                # 解析方式 1b: 使用OpenAI风格的格式
                                elif 'choices' in json_data and len(json_data['choices']) > 0:
                                    delta = json_data['choices'][0].get('delta', {})
                                    content = delta.get('content', '')
                                    
                                    if content:
                                        logger.debug(f"提取的OpenAI风格内容块: {content}")
                                        buffer += content
                                        full_response += content
                                        yield content
                                        
                                # 解析方式 1c: 其他code处理
                                elif json_data.get('code') in [201, 203]:
                                    # 流开始或结束标记
                                    logger.debug(f"收到流控制标记 code={json_data.get('code')}")
                                    
                                # 解析方式 1d: 直接尝试提取content字段
                                elif 'content' in json_data:
                                    content = json_data['content']
                                    if content:
                                        logger.debug(f"直接提取content字段: {content}")
                                        buffer += content
                                        full_response += content
                                        yield content
                            except json.JSONDecodeError as e:
                                logger.warning(f"无法解析JSON数据({e}): {data}")
                        
                        # 解析方式 2: 尝试直接解析每一行为JSON
                        elif line_text.strip():
                            try:
                                direct_json = json.loads(line_text.strip())
                                logger.debug(f"直接解析行为JSON: {direct_json}")
                                
                                # 提取可能的内容
                                if 'content' in direct_json:
                                    content = direct_json['content']
                                    logger.debug(f"从直接JSON中提取内容: {content}")
                                    buffer += content
                                    full_response += content
                                    yield content
                                elif 'data' in direct_json and isinstance(direct_json['data'], dict):
                                    if 'content' in direct_json['data']:
                                        content = direct_json['data']['content']
                                        logger.debug(f"从嵌套JSON中提取内容: {content}")
                                        buffer += content
                                        full_response += content
                                        yield content
                            except json.JSONDecodeError:
                                # 忽略非JSON行
                                pass
                    
                    logger.debug(f"响应处理完成，共收到 {line_count} 行数据")
                    
                    # 如果没有成功解析任何内容，尝试替代解析方法
                    if not full_response:
                        logger.warning("常规解析未能提取内容，尝试备用解析方法")
                        
                        # 备用方法：搜索包含"content"的行
                        content_fragments = []
                        for line in raw_lines:
                            if '"content":"' in line or '"content": "' in line:
                                logger.debug(f"找到包含content的行: {line}")
                                try:
                                    # 尝试提取content值
                                    start_idx = line.find('"content":"') + 11
                                    if start_idx < 11:  # 如果没找到，尝试带空格的版本
                                        start_idx = line.find('"content": "') + 12
                                    
                                    if start_idx > 11:  # 如果找到了
                                        end_idx = line.find('"', start_idx)
                                        if end_idx > start_idx:
                                            content = line[start_idx:end_idx]
                                            logger.debug(f"使用字符串搜索提取content: {content}")
                                            content_fragments.append(content)
                                except Exception as e:
                                    logger.warning(f"备用解析内容时出错: {str(e)}")
                        
                        if content_fragments:
                            full_text = "".join(content_fragments)
                            logger.debug(f"备用方法提取的完整内容: {full_text}")
                            yield full_text
                            full_response = full_text
                    
                    # 更新会话历史
                    if full_response:
                        try:
                            # 添加用户消息到历史
                            history = self.conversations.get(session_id, [])
                            history.append({"role": "user", "content": message})
                            # 添加AI回复到历史
                            history.append({"role": "assistant", "content": full_response})
                            # 更新会话历史
                            self.conversations[session_id] = history
                            logger.debug(f"已更新会话历史，当前长度: {len(history)}")
                        except Exception as e:
                            logger.warning(f"更新会话历史出错: {str(e)}")
                    else:
                        logger.warning("未收到有效回复内容")
                        
            except asyncio.TimeoutError:
                logger.error("聊天请求超时")
                yield "请求超时，请稍后再试"
            except Exception as e:
                logger.error(f"聊天请求异常: {str(e)}")
                yield f"请求异常: {str(e)}"
                
    async def generate_image(self, session_id: str, prompt: str, model: str = None, 
                           ratio: str = "1:1", web_access: str = "close", 
                           timezone: str = "Asia/Shanghai") -> AsyncGenerator[str, None]:
        """生成图片
        
        Args:
            session_id: 会话ID
            prompt: 图片描述提示词
            model: 使用的模型，为空则使用默认图片模型
            ratio: 图片比例，默认1:1
            web_access: 网络访问设置
            timezone: 时区设置
            
        Yields:
            str: 包含生成进度和最终图片链接的消息片段
        """
        url = f"{self.base_url}/api/v2/chat/conversation"
        
        # 如果未指定模型，使用默认图片模型
        model_to_use = model if model else "openai/gpt-4o-image"
        
        # 准备请求体
        payload = {
            "model": model_to_use,
            "prompt": prompt,
            "webAccess": web_access,
            "timezone": timezone
        }
        
        if ratio:
            payload["ratio"] = ratio
            
        headers = self._get_headers()
        logger.debug(f"发送图片生成请求，payload: {payload}")
        
        image_url = None  # 保存提取的图片URL
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, headers=headers, json=payload, timeout=180) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"图片生成请求失败: {response.status} - {error_text}")
                        yield f"API错误: {response.status}"
                        return
                    
                    logger.debug(f"收到图片生成响应，content-type: {response.headers.get('content-type')}")
                    
                    # 读取SSE响应
                    progress_info = ""
                    markdown_image = ""
                    line_count = 0
                    
                    async for line in response.content:
                        line_text = line.decode('utf-8')
                        line_count += 1
                        
                        # 每5行打印一次原始数据以便调试
                        if line_count <= 10 or line_count % 20 == 0:
                            logger.debug(f"图片生成响应行 {line_count}: {line_text}")
                        
                        # 解析 data: 前缀
                        if line_text.startswith('data:'):
                            data = line_text[5:].strip()
                            
                            if data == "[DONE]":
                                logger.debug("收到[DONE]标记")
                                break
                                
                            try:
                                json_data = json.loads(data)
                                
                                # 检查是否是进度更新
                                if json_data.get('code') == 202 and 'data' in json_data:
                                    data_obj = json_data['data']
                                    if data_obj.get('type') == 'chat' and 'content' in data_obj:
                                        content = data_obj['content']
                                        if content:
                                            # 检查是否是进度信息
                                            if "进度" in content or "%" in content or "生成中" in content or "排队中" in content:
                                                # 更新进度信息
                                                progress_info = content
                                                yield content
                                                
                                            # 检查是否包含图片URL (Markdown格式)
                                            elif "![" in content and "](http" in content:
                                                markdown_image = content
                                                # 提取图片URL
                                                start_idx = content.find("](") + 2
                                                end_idx = content.find(")", start_idx)
                                                if start_idx > 1 and end_idx > start_idx:
                                                    image_url = content[start_idx:end_idx]
                                                    logger.info(f"提取到图片URL: {image_url}")
                                                yield content
                                            else:
                                                yield content
                            except json.JSONDecodeError:
                                pass
                    
                    logger.debug(f"图片生成响应处理完成，共收到 {line_count} 行数据")
                    
                    # 如果找到了图片URL，可以在这里下载保存
                    if image_url and session_id:
                        try:
                            # 添加用户提示和AI回复到历史
                            history = self.conversations.get(session_id, [])
                            # 用户消息
                            history.append({"role": "user", "content": f"生成图片: {prompt}"})
                            # AI回复 (包含图片的Markdown)
                            history.append({"role": "assistant", "content": markdown_image})
                            # 更新会话历史
                            self.conversations[session_id] = history
                            logger.debug(f"已更新图片生成历史，当前长度: {len(history)}")
                        except Exception as e:
                            logger.warning(f"更新图片生成历史出错: {str(e)}")
                        
            except asyncio.TimeoutError:
                logger.error("图片生成请求超时")
                yield "图片生成请求超时，请稍后再试"
            except Exception as e:
                logger.error(f"图片生成请求异常: {str(e)}")
                yield f"图片生成请求异常: {str(e)}"
                
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头
        
        Returns:
            Dict[str, str]: HTTP请求头
        """
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0",
            "Origin": "chrome-extension://minfmdkpoboejckenbchpjbjjkbdebdm",
            "i-lang": self.language,
            "i-version": self.client_version,
            "sec-ch-ua": "\"Chromium\";v=\"134\", \"Not:A-Brand\";v=\"24\", \"Microsoft Edge\";v=\"134\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site"
        }
    
    def clear_conversation(self, session_id: str) -> None:
        """清除特定会话的历史记录
        
        Args:
            session_id: 会话ID
        """
        if session_id in self.conversations:
            del self.conversations[session_id]
    
    def set_default_model(self, model: str) -> None:
        """设置默认模型
        
        Args:
            model: 模型名称，格式为"提供商/模型名"
        """
        self.default_model = model
        logger.info(f"默认模型已更新为: {model}")
            
    def get_conversation_history(self, session_id: str) -> List[Dict]:
        """获取会话历史
        
        Args:
            session_id: 会话ID
            
        Returns:
            List[Dict]: 会话历史消息列表
        """
        return self.conversations.get(session_id, []) 
import os
import hashlib
from typing import Optional
from PIL import Image, ImageDraw
from astrbot.api import logger

async def get_user_avatar(user_id: str, data_dir: str, avatar_size: int = 50, avatar_config: dict = None) -> Optional[Image.Image]:
    """
    获取用户头像并处理为圆形
    
    Args:
        user_id: 用户ID
        data_dir: 插件的数据目录
        avatar_size: 头像尺寸
        avatar_config: 头像配置字典，包含source、server_url和access_token
    
    Returns:
        处理后的头像图像，如果失败返回None
    """
    try:
        import aiohttp
        from io import BytesIO
        import time
        
        # 创建头像缓存目录
        cache_dir = os.path.join(data_dir, "avatar_cache")
        os.makedirs(cache_dir, exist_ok=True)
        
        # 安全化user_id用于文件名
        import re
        safe_user_id = re.sub(r'[^a-zA-Z0-9._-]', '_', user_id)
        safe_user_id = re.sub(r'_+', '_', safe_user_id).strip('_') or 'unknown'
        avatar_cache_path = os.path.join(cache_dir, f"{safe_user_id}_avatar.png")
        
        # 检查是否有缓存的头像（24小时刷新）
        avatar_image = None
        if os.path.exists(avatar_cache_path):
            try:
                file_age = time.time() - os.path.getmtime(avatar_cache_path)
                if file_age < 86400:  # 24小时
                    avatar_image = Image.open(avatar_cache_path).convert('RGBA')
            except:
                pass

        if avatar_image is None:
            avatar_source = avatar_config.get('source', 'qq') if avatar_config else 'qq'
            
            if avatar_source == 'matrix' and avatar_config:
                server_url = avatar_config.get('server_url', '')
                access_token = avatar_config.get('access_token', '')

                if server_url and access_token:
                    try:
                        timeout = aiohttp.ClientTimeout(total=10, connect=5)
                        async with aiohttp.ClientSession(timeout=timeout) as session:
                            profile_url = f"{server_url}/_matrix/client/v3/profile/{user_id}"

                            async with session.get(profile_url, headers={"Authorization": f"Bearer {access_token}"}) as response:
                                if response.status == 200:
                                    try:
                                        profile_data = await response.json()
                                    except Exception:
                                        logger.warning(f"[Matrix Avatar] 解析profile响应失败: {user_id}")
                                        return None
                                    avatar_url = profile_data.get('avatar_url', '')

                                    if avatar_url and avatar_url.startswith('mxc://'):
                                        mxc_parts = avatar_url.replace('mxc://', '').split('/')
                                        if len(mxc_parts) < 2:
                                            logger.warning(f"[Matrix Avatar] 无效的avatar_url格式: {avatar_url}")
                                            return None
                                        media_server, media_id = mxc_parts[0], mxc_parts[1]
                                        if not media_server or not media_id:
                                            logger.warning(f"[Matrix Avatar] avatar_url解析后server或media_id为空: {avatar_url}")
                                            return None
                                        media_url = f"{server_url}/_matrix/client/v1/media/download/{media_server}/{media_id}"
                                        headers = {"Authorization": f"Bearer {access_token}"}
                                        async with session.get(media_url, headers=headers) as avatar_response:
                                            if avatar_response.status == 200:
                                                content = await avatar_response.read()
                                                avatar_image = Image.open(BytesIO(content)).convert('RGBA')
                                                avatar_image.save(avatar_cache_path, 'PNG')
                                            elif avatar_response.status == 404:
                                                logger.warning(f"[Matrix Avatar] 媒体文件不存在: {media_url}")
                                                return None
                                            elif avatar_response.status == 403:
                                                logger.warning(f"[Matrix Avatar] 无权限访问媒体文件")
                                                return None
                                            else:
                                                logger.warning(f"[Matrix Avatar] 媒体下载失败，状态码: {avatar_response.status}")
                                                return None
                                    elif avatar_url:
                                        logger.warning(f"[Matrix Avatar] 未知的avatar_url格式: {avatar_url}")
                                        return None
                                elif response.status == 404:
                                    logger.warning(f"[Matrix Avatar] 用户不存在: {user_id}")
                                    return None
                                elif response.status == 401:
                                    logger.warning(f"[Matrix Avatar] Token无效或已过期")
                                    return None
                                elif response.status == 429:
                                    logger.warning(f"[Matrix Avatar] 请求过于频繁，被限流")
                                    return None
                                else:
                                    logger.warning(f"[Matrix Avatar] Profile API返回错误状态码: {response.status}")
                                    return None
                    except Exception as e:
                        logger.warning(f"[Matrix Avatar] Matrix头像下载失败: {e}")
            else:
                avatar_url = f"https://q4.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"
                try:
                    timeout = aiohttp.ClientTimeout(total=10, connect=5)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(avatar_url) as response:
                            if response.status == 200:
                                content = await response.read()
                                avatar_image = Image.open(BytesIO(content)).convert('RGBA')
                                avatar_image.save(avatar_cache_path, 'PNG')
                except Exception as e:
                    logger.warning(f"QQ头像下载失败: {e}")
                    return None

        if avatar_image:
            return avatar_postprocess(avatar_image, avatar_size)
        
    except Exception as e:
        logger.warning(f"[Matrix Avatar] 获取用户头像失败: {e}, user_id={user_id}")
    
    return None

def avatar_postprocess(avatar_image: Image.Image, size: int) -> Image.Image:
    """
    将头像处理为指定大小的圆角头像
    """
    # 调整头像大小
    avatar_image = avatar_image.resize((size, size), Image.Resampling.LANCZOS)
    
    # 使用更合适的圆角半径
    corner_radius = size // 8  # 稍微减小圆角，看起来更自然
    
    # 抗锯齿处理
    scale_factor = 4
    large_size = size * scale_factor
    large_radius = corner_radius * scale_factor
    
    # 创建高质量遮罩
    large_mask = Image.new('L', (large_size, large_size), 0)
    large_draw = ImageDraw.Draw(large_mask)
    
    # 绘制圆角矩形
    large_draw.rounded_rectangle(
        [0, 0, large_size, large_size], 
        radius=large_radius, 
        fill=255
    )
    
    # 高质量缩放
    mask = large_mask.resize((size, size), Image.Resampling.LANCZOS)
    avatar_image.putalpha(mask)
    
    return avatar_image

async def get_fish_icon(icon_url: str, data_dir: str, icon_size: int = 60) -> Optional[Image.Image]:
    """
    下载并处理鱼类图标
    
    Args:
        icon_url: 图标URL
        data_dir: 插件的数据目录
        icon_size: 图标尺寸
    
    Returns:
        处理后的图标图像，如果失败返回None
    """
    if not icon_url or not icon_url.strip():
        return None
    
    try:
        import aiohttp
        from io import BytesIO
        import time
        
        # 创建图标缓存目录
        cache_dir = os.path.join(data_dir, "fish_icon_cache")
        os.makedirs(cache_dir, exist_ok=True)
        
        # 使用URL的hash作为缓存文件名
        url_hash = hashlib.md5(icon_url.encode()).hexdigest()
        icon_cache_path = os.path.join(cache_dir, f"{url_hash}.png")
        
        # 检查是否有缓存的图标（7天刷新）
        icon_image = None
        if os.path.exists(icon_cache_path):
            try:
                file_age = time.time() - os.path.getmtime(icon_cache_path)
                if file_age < 604800:  # 7天
                    icon_image = Image.open(icon_cache_path).convert('RGBA')
            except:
                pass
        
        # 如果没有缓存或缓存过期，重新下载
        if icon_image is None:
            try:
                timeout = aiohttp.ClientTimeout(total=10, connect=5)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(icon_url.strip()) as response:
                        if response.status == 200:
                            content = await response.read()
                            # 限制文件大小（最大5MB）
                            if len(content) > 5 * 1024 * 1024:
                                logger.warning(f"图标文件过大，跳过: {icon_url}")
                                return None
                            icon_image = Image.open(BytesIO(content)).convert('RGBA')
                            # 保存到缓存
                            icon_image.save(icon_cache_path, 'PNG')
                        else:
                            logger.warning(f"下载图标失败，HTTP状态码: {response.status}, URL: {icon_url}")
                            return None
            except Exception as e:
                # 如果下载失败，记录日志但不抛出异常
                logger.warning(f"图标下载失败: {e}, URL: {icon_url}")
                return None
        
        if icon_image:
            # 调整图标大小并保持宽高比
            icon_image.thumbnail((icon_size, icon_size), Image.Resampling.LANCZOS)
            return icon_image
        
    except Exception as e:
        logger.warning(f"处理图标时发生错误: {e}, URL: {icon_url}")
    
    return None

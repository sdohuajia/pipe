import logging
import json
import aiohttp
import asyncio
from datetime import datetime, timedelta
import sys

# ANSI 转义序列
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    RESET = "\033[0m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

# 基础配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
BASE_URL = "https://pipe-network-backend.pipecanary.workers.dev/api"

# 时间间隔配置
HEARTBEAT_INTERVAL = 300  # 5分钟
TEST_INTERVAL = 30 * 60  # 30分钟
RETRY_DELAY = 5  # 重试延迟（秒）

# 代理配置
PROXY_FILE = "proxy.txt"

async def load_tokens_with_emails():
    """从token.txt文件中加载多个token和邮箱映射"""
    try:
        with open('token.txt', 'r') as file:
            token_email_mapping = {}
            for line in file:
                parts = line.strip().split(',')
                if len(parts) == 2:
                    token, email = parts
                    token_email_mapping[token] = email
            return token_email_mapping
    except FileNotFoundError:
        logging.error("token.txt文件未找到")
    except Exception as e:
        logging.error(f"从token.txt文件加载tokens和邮箱时发生错误: {e}")
    return {}

async def load_proxies():
    """从proxy.txt文件中加载多个代理"""
    try:
        with open(PROXY_FILE, 'r') as file:
            proxies = [line.strip() for line in file if line.strip()]
            return proxies
    except FileNotFoundError:
        logging.warning("proxy.txt文件未找到,将不使用代理")
    except Exception as e:
        logging.error(f"从proxy.txt文件加载代理时发生错误: {e}")
    return []

async def get_ip(proxy=None):
    """获取当前IP地址,可以使用代理"""
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        if proxy:
            session._connector._proxy = proxy
        try:
            async with session.get("https://api64.ipify.org?format=json", timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('ip')
        except Exception as e:
            logging.error(f"获取IP失败: {e}")
            await asyncio.sleep(RETRY_DELAY)
    return None

async def send_heartbeat(token, proxy=None):
    """发送心跳信号,可以使用代理"""
    # 隐藏心跳发送信息
    ip = await get_ip(proxy)
    if not ip:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = {"ip": ip}
    
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        if proxy:
            session._connector._proxy = proxy
        try:
            async with session.post(f"{BASE_URL}/heartbeat", headers=headers, json=data, timeout=5) as response:
                if response.status == 200:
                    pass  # 不打印心跳发送成功信息
                elif response.status == 429:
                    return  # 静默处理限流错误
        except Exception as e:
            pass  # 不打印心跳发送错误信息

async def fetch_points(token, proxy=None):
    """获取当前分数,可以使用代理"""
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        if proxy:
            session._connector._proxy = proxy
        try:
            async with session.get(f"{BASE_URL}/points", headers=headers, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('points')
        except Exception as e:
            logging.error(f"获取分数时发生错误: {e}")
            await asyncio.sleep(RETRY_DELAY)
    return None

async def test_all_nodes(nodes, proxy=None):
    """同时测试所有节点,可以使用代理"""
    async def test_single_node(node):
        try:
            start = asyncio.get_event_loop().time()
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                if proxy:
                    session._connector._proxy = proxy
                async with session.get(f"http://{node['ip']}", timeout=5) as node_response:
                    latency = (asyncio.get_event_loop().time() - start) * 1000
                    status = "在线" if node_response.status == 200 else "离线"
                    latency_value = latency if status == "在线" else -1
                    return (node['node_id'], node['ip'], latency_value, status)
        except (asyncio.TimeoutError, aiohttp.ClientConnectorError):
            return (node['node_id'], node['ip'], -1, "离线")

    tasks = [test_single_node(node) for node in nodes]
    return await asyncio.gather(*tasks)

async def report_node_result(token, node_id, ip, latency, status, proxy=None):
    """报告单个节点的测试结果,可以使用代理"""
    # 隐藏报告节点测试结果时的错误信息
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    test_data = {
        "node_id": node_id,
        "ip": ip,
        "latency": latency,
        "status": status
    }
    
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        if proxy:
            session._connector._proxy = proxy
        try:
            async with session.post(f"{BASE_URL}/test", headers=headers, json=test_data, timeout=5) as response:
                if response.status == 200:
                    return
                # 不打印错误信息
        except Exception as e:
            pass  # 不打印错误信息

async def report_all_node_results(token, results, proxy=None):
    """报告所有节点的测试结果,可以使用代理"""
    for node_id, ip, latency, status in results:
        await report_node_result(token, node_id, ip, latency, status, proxy)

async def start_testing(token, proxy=None):
    """开始测试流程,可以使用代理"""
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        if proxy:
            session._connector._proxy = proxy
        try:
            async with session.get(f"{BASE_URL}/nodes", headers={"Authorization": f"Bearer {token}"}, timeout=5) as response:
                if response.status == 200:
                    nodes = await response.json()
                    results = await test_all_nodes(nodes, proxy)
                    await report_all_node_results(token, results, proxy)
                    return
                # 不打印错误信息
        except Exception as e:
            pass  # 不打印错误信息

async def register_account():
    """注册新账户"""
    print("\n=== 账户注册 ===")
    email = input("请输入邮箱: ")
    password = input("请输入密码: ")
    invite_code = input("请输入邀请码: ")
    
    async with aiohttp.ClientSession() as session:
        try:
            data = {
                "email": email,
                "password": password,
                "invite_code": invite_code
            }
            proxy = await load_proxies()
            if proxy:
                session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))
                session._connector._proxy = proxy[0]
            async with session.post(f"{BASE_URL}/signup", json=data, timeout=5) as response:
                if response.status in [200, 201]:
                    result = await response.json()
                    token = result.get('token')
                    print(f"\n注册成功！您的token是: {token}")
                    print("请保存此信息到tokenz.txt文件中")
                    
                    save = input("\n是否自动保存注册信息到tokenz.txt？(y/n): ")
                    if save.lower() == 'y':
                        try:
                            with open('tokenz.txt', 'a') as f:
                                f.write(f"{token},{email}\n")
                            print("token和邮箱已成功添加到tokenz.txt")
                        except Exception as e:
                            print(f"保存token和邮箱时发生错误: {e}")
                    return
                # 不打印错误信息
        except Exception as e:
            pass  # 不打印错误信息

async def display_menu():
    """显示主菜单"""
    while True:
        print("\n" + "="*50)
        print(f"{Colors.CYAN}*X:https://x.com/ferdie_jhovie*")
        print(f"首发pipe network脚本，盗脚本可耻，请标注出处")
        print(f"*Tg:https://t.me/sdohuajia*{Colors.RESET}")
        print("="*50)
        print(f"\n{Colors.CYAN}请选择功能:{Colors.RESET}")
        print(f"{Colors.WHITE}1. 运行节点{Colors.RESET}")
        print(f"{Colors.WHITE}2. 注册账户{Colors.RESET}")
        print(f"{Colors.WHITE}3. 退出程序\n{Colors.RESET}")
        
        choice = input("请输入选项 (1-3): ")
        
        if choice == "1":
            await run_node()
        elif choice == "2":
            await register_account()
        elif choice == "3":
            print("\n感谢使用，再见！")
            sys.exit(0)
        else:
            print("\n无效选项，请重试")

async def run_node():
    """运行节点测试并显示多个token的分数"""
    token_email_mapping = await load_tokens_with_emails()
    if not token_email_mapping:
        logging.error("无法加载tokens和邮箱。请确保token.txt文件存在且包含有效的tokens和邮箱。")
        return

    proxies = await load_proxies()
    
    logging.info("Tokens和邮箱加载成功!")
    
    next_heartbeat_time = datetime.now()
    next_test_time = datetime.now()
    first_heartbeat = True
    
    try:
        while True:
            current_time = datetime.now()
            
            if current_time >= next_heartbeat_time:
                if first_heartbeat:
                    logging.info("开始首次心跳...")
                    first_heartbeat = False
                for i, (token, email) in enumerate(token_email_mapping.items()):
                    proxy = proxies[i] if i < len(proxies) else None
                    await send_heartbeat(token, proxy)
                next_heartbeat_time = current_time + timedelta(seconds=HEARTBEAT_INTERVAL)
            
            if current_time >= next_test_time:
                for i, (token, email) in enumerate(token_email_mapping.items()):
                    proxy = proxies[i] if i < len(proxies) else None
                    if proxy:
                        print(f"{Colors.CYAN}使用代理进行节点测试: {proxy}{Colors.RESET}")
                    else:
                        print(f"{Colors.CYAN}使用本地直连进行节点测试{Colors.RESET}")
                    await start_testing(token, proxy)
                    current_points = await fetch_points(token, proxy)
                    if current_points is not None:
                        print(f"{Colors.GREEN}邮箱: {email} 测试节点循环完成后当前分数: {current_points}{Colors.RESET}")
                next_test_time = current_time + timedelta(seconds=TEST_INTERVAL)
            
            remaining_time = next_test_time - current_time
            if remaining_time.total_seconds() > 0:
                print(f"\r{Colors.WHITE}等待下一轮测试，剩余时间: {remaining_time}{Colors.RESET}", end="")
            else:
                print(f"\r{Colors.WHITE}下一轮测试即将开始{Colors.RESET}", end="")
            
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n返回主菜单...")

async def main():
    print("""
*****************************************************
*           X:https://x.com/ferdie_jhovie           *
*           Tg:https://t.me/sdohuajia               *
*****************************************************
""")
    
    await display_menu()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已退出")
        sys.exit(0)

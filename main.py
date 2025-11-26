from langchain_community.chat_models import ChatZhipuAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.tools import tool
from langchain.agents import create_agent
import os
import re
import pymysql
from collections import Counter
import datetime

ZHI_PU_API_KEY = os.environ.get("ZHI_PU_API_KEY")
llm = ChatZhipuAI(model="glm-4-flashx", api_key=ZHI_PU_API_KEY)
types = [
    "commentary", "size", "return_exchange", "modify_information",
    "manual_docking"
]

DB_CONFIG = {
    'host': 'localhost',
    'database': 'shop_db',
    'user': 'root',
    'password': '123456'
}


def execute_query(query, params: tuple = None, cursors=None):
    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor(cursors) as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
    except Exception as e:
        print(f"数据库查询错误: {e}")
        return []


def get_attribute_key():
    query = "SELECT DISTINCT attribute_key FROM product_attributes"
    return [re[0] for re in execute_query(query)]


attribute_list = get_attribute_key()


def product_attribute(product_id: int, attribute_key: str):
    query = "SELECT attribute_value FROM product_attributes WHERE product_id = %s AND attribute_key = %s"
    return execute_query(query, (product_id, attribute_key))


def attribute(attribute_key: str):
    query = "SELECT product_id, attribute_value FROM product_attributes WHERE attribute_key = %s"
    return execute_query(query, (attribute_key, ))


def purchases_sizes(product_id: int, height: int, weight: int):
    query = "SELECT size_code FROM product_purchases WHERE product_id = %s AND ABS(height - %s) <= 10 AND ABS(weight - %s) <= 10 AND return_item = 0 AND status = 'delivered'"
    return execute_query(query, (product_id, height, weight))


def product_sizes(product_id: int):
    query = """
    SELECT size_code, height_range,
    weight_range, length, sleeve_length,
    bust, waist, hip, bottom_hem
    FROM product_sizes
    WHERE product_id = %s AND stock != 0;
    """
    return execute_query(query, (product_id, ), pymysql.cursors.DictCursor)


def product_order_info(id: int):
    query = """
    SELECT purchase_date
    FROM product_purchases  
    WHERE id = %s
    """
    return execute_query(query, (id, ))

@tool
def get_product_attribute_value(product_id: int, attribute_key: str):
    """
    获取指定商品的指定属性信息
    
    Args:
        product_id (int): 商品ID
        attribute_key (str): 属性名称
    
    Returns:
        str: 属性值
    """
    return product_attribute(product_id, attribute_key)


@tool
def get_attribute_value(attribute_key: str):
    """
    获取所有商品的指定属性信息
    
    Args:
        attribute_key (str): 属性名称
    
    Returns:
        str: 属性值
    """
    return attribute(attribute_key)


@tool
def get_purchases_sizes(product_id: int, height: int, weight: int):
    """
    获取购买过此产品的买家的身高体重以及所购买的尺寸
    
    Args:
        product_id (int): 商品ID
        height (int): 身高
        weight (int): 体重
    
    Returns:
        height (int): 身高
        weight (int): 体重
        str: 尺寸信息
    """
    return purchases_sizes(product_id, height, weight)


@tool
def get_product_sizes(product_id: int):
    """
    获取指定商品的所有尺寸信息
    """
    return product_sizes(product_id)


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    type: str


builder = StateGraph(State)


def supervisor_node(state: State):
    if 'type' in state:
        return {"type": END}
    system_prompt = """
    你是一个分类助手,请根据输入返回分类结果,分类根据如下
    如果提问的是商品相关的提问,请返回commentary,
    如果提问的是尺寸相关的提问,请返回size,
    如果提问的是退换货相关问题,请返回return_exchange,
    如果提问的是修改订单信息相关问题,请返回modify_information,
    如果提问的是人工对接相关问题,以及如果跟上述4类无关系,请返回manual_docking,
    请根据输入返回对应的分类结果,请勿返回其他内容
    """
    prompt = [{
        "role": "system",
        "content": system_prompt
    }, {
        "role": "user",
        "content": state["messages"][0].content
    }]
    response = llm.invoke(prompt)
    type_res = response.content
    if type_res in types:
        return {"type": type_res}


def commentary_node(state: State):
    system_prompt = f"""
你是一名专业的电商平台客服人员，请根据用户提出的问题，直接调用工具搜索相关商品信息，并以亲切、专业、简洁的客服口吻，将搜索结果清晰地回复给用户。
属性值包含{attribute_list}
回复内容应体现服务意识，使用如“亲亲”“您好”等常见电商客服用语，但不要提出反问或引导性问题，只需基于工具返回的信息作答即可。
"""
    prompt = [{
        "role": "system",
        "content": system_prompt
    }, {
        "role": "user",
        "content": state["messages"][0].content
    }]
    agent = create_agent(model=llm,
                         tools=[
                             get_product_attribute_value,
                             get_attribute_value,
                         ])
    response = agent.invoke({"messages": prompt})
    print(response)
    return {"messages": [AIMessage(content=response["messages"][-1].content)]}


def size_node(state: State):
    messages = state["messages"][0].content
    product_id_match = re.search(r'商品\s*(?:id|ID|编号)\s*[:：=为是]?\s*(\d+)',messages)
    product_id = product_id_match.group(1) if product_id_match else None
    height_match = re.search(r'身高\s*[:：]?\s*(\d{2,3})', messages)
    height = height_match.group(1) if height_match else None
    weight_match = re.search(r'体重\s*[:：]?\s*(\d{1,3})', messages)
    weight = weight_match.group(1) if height_match else None
    if product_id and height and weight:
        sizes = purchases_sizes(product_id, height, weight)
        values = [item[0] for item in sizes]
        if len(values) <= 5:
            sizes = product_sizes(product_id)
            size_table = []
            for size in sizes:
                height_min, height_max = size['height_range'].split('-')
                weight_min, weight_max = size['weight_range'].split('-')
                size_table.append((height_min, height_max,weight_min, weight_max, size['size_code']))
            for h_min, h_max, w_min, w_max, result in size_table:
                if h_min <= height <= h_max and weight <= w_max:
                    return {"messages": [AIMessage(content=f"亲,根据商品参照表,建议您可以选择{result}码哦")]}
        else:
            counter = Counter(values)
            max_count = max(counter.values())
            result = max(k for k,v in counter.items() if v == max_count)
            return {"messages": [AIMessage(content=f"亲，根据购买过此商品的买家信息，大部分与您身材相仿的都选择{result}码了，所以建议您可以选择{result}码哦")]}
    else:
        system_prompt = "你是一个专业的电商平台客服人员，请根据用户提出问题，返回尺寸建议。"
        prompt = [{
            "role": "system",
            "content": system_prompt
        }, {
            "role": "user",
            "content": state["messages"][0].content
        }]


def return_exchange_node(state: State):
    """
    处理退换货:判断是否是质量问题以及是否超出无理由退换时间，如果判断为质量问题则切换到manual_docking_node
    """
    messages = state["messages"][0].content
    order_id_match = re.search(r'订单\s*?(?:id|ID|号|编号)\s*?[;:=为是]?\s*(\d+)',
                               messages)
    order_id = order_id_match.group(1) if order_id_match else None
    if not order_id:
        return {"messages": [AIMessage(content="亲亲，请提供具体商品ID以便我们为您查询退换货政策哦~")]}
    quality_keywords = [
        "破损", "开线", "掉色", "发错", "少发", "质量问题", "瑕疵", "坏的", "不能用"
    ]
    is_quality_issue = any(kw in messages for kw in quality_keywords)
    # 获取订单信息
    order = product_order_info(order_id)
    if not order:
        return {
            "messages": [AIMessage(content="亲亲，未查询到该商品的购买记录，请确认是否在本店购买哦~")]
        }
    now = datetime.datetime.now()
    days_since_order = (now - order[0][0]).days
    if is_quality_issue:
        return {
            "messages":
            [AIMessage(content="亲亲，您反馈的是质量问题，我们将为您转接人工客服专员处理，请稍等~")],
            "type": "manual_docking"
        }
    if days_since_order <= 7:
        print("订单符合7天无理由退换条件")
        return {"messages": [AIMessage(content="亲亲，您的订单符合7天无理由退换条件，请在【我的订单】中提交退换申请，我们会尽快处理哦~")],"type":"supervisor    "}
    else:
        return {"messages": [AIMessage(content="亲亲，很抱歉，您的订单已超过7天无理由退换期限，且不属于质量问题，暂时无法办理退换呢。如有特殊情况，可联系人工客服协助~")], "type": "manual_docking"}

def manual_docking_node(state: State):
    """
    人工对接节点：使用 LLM 对用户问题和上下文进行智能摘要，生成便于人工客服理解的简报。
    同时保留关键结构化字段供系统使用。
    """
    messages = state.get("messages", [])
    user_query = messages[0].content if messages else "无用户输入"
    problem_type = state.get("type", "未知类型")

    # 使用 LLM 生成自然语言摘要
    summary_prompt = f"""
你是一名电商平台的智能助手，请根据以下用户问题，生成一段简洁明了的客服转接摘要。
摘要需包含：用户意图、涉及的商品或订单（如有）、关键描述（如质量问题、尺寸困惑等），语气专业清晰。
不要使用 markdown，不要编号，直接输出一段话。

用户问题：{user_query}
问题类型：{problem_type}
"""

    try:
        llm_response = llm.invoke([{"role": "user", "content": summary_prompt}])
        natural_summary = llm_response.content.strip()
    except Exception as e:
        print(f"LLM 摘要生成失败: {e}")
        natural_summary = f"（自动生成摘要失败）原始问题：{user_query}"

    # 同时提取结构化字段（用于日志/工单系统）
    order_id_match = re.search(r'订单\s*?(?:id|ID|号|编号)\s*?[;:=为是]?\s*(\d+)', user_query)
    product_id_match = re.search(r'商品\s*(?:id|ID|编号)\s*[:：=为是]?\s*(\d+)', user_query)

    structured_data = {
        "user_query": user_query,
        "problem_type": problem_type,
        "order_id": order_id_match.group(1) if order_id_match else None,
        "product_id": product_id_match.group(1) if product_id_match else None,
        "llm_summary": natural_summary,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    response_text = (
        "亲亲，您的问题比较特殊，已为您转接人工客服专员处理~\n"
        "我们已将您的问题摘要提交给客服团队，他们会尽快与您联系，请保持在线哦！"
    )

    return {"messages": [AIMessage(content=response_text)]}


def routing_fanc(state: State):
    if state["type"] == "commentary":
        return "commentary_node"
    elif state["type"] == "size":
        return "size_node"
    elif state["type"] == "return_exchange":
        return "return_exchange_node"
    elif state["type"] == "modify_information":
        return "modify_information_node"
    elif state["type"] == "manual_docking":
        return "manual_docking_node"
    elif state["type"] == END:
        return END
    else:
        return "manual_docking_node"

def docking_fanc(state: State):
    if state["type"] == "manual_docking":
        return "manual_docking_node"
    elif state["type"] == "supervisor":
        return 'supervisor_node'

builder.add_node("supervisor_node", supervisor_node)
builder.add_node("commentary_node", commentary_node)
builder.add_node("size_node", size_node)
builder.add_node("return_exchange_node", return_exchange_node)
builder.add_node("modify_information_node", modify_information_node)
builder.add_node("manual_docking_node", manual_docking_node)

builder.add_edge(START, "supervisor_node")
builder.add_conditional_edges("supervisor_node", routing_fanc, [
    "commentary_node", "size_node", "return_exchange_node",
    "modify_information_node", "manual_docking_node", END
])
builder.add_edge("commentary_node", "supervisor_node")
builder.add_edge("size_node", "supervisor_node")
builder.add_edge("modify_information_node", "supervisor_node")
builder.add_edge("manual_docking_node", "supervisor_node")
builder.add_conditional_edges("return_exchange_node",docking_fanc, ["manual_docking_node","supervisor_node"])

checkpointer = InMemorySaver()

graph = builder.compile(checkpointer=checkpointer)

if __name__ == "__main__":
    # print(product_sizes(1))
    config = {"configurable": {"thread_id": "1"}}
    user_input = {"messages": [HumanMessage(content="我要退掉订单号为1的商品")]}
    for chunk in graph.stream(user_input, config, stream_mode="updates"):
        print(chunk)
# 商品id为2的商品是什么款式的？
# 都有哪些款式的衣服？
# 都有哪些衣服有红色的？
# 都有红色的裤子有哪些？
# 商品id为1的商品,我身高192,体重83kg买哪个尺码比较合适?
# 商品id为1的商品都有什么尺寸的？都适合什么身高体重？
# 商品id为1的商品,我身高192,体重87kg买哪个尺码比较合适?
# 我要退掉订单号为1的商品

from linebot import LineBotApi, WebhookHandler
from linebot.models import TextSendMessage
from firebase import firebase
from linebot.models import ImageSendMessage
from linebot.models import StickerMessage, StickerSendMessage
from opencc import OpenCC
from bs4 import BeautifulSoup
from io import BytesIO
import base64
import google.generativeai as genai
import json
import os
import requests
import re

# 使用環境變量讀取憑證
token = os.getenv('LINE_BOT_TOKEN')
secret = os.getenv('LINE_BOT_SECRET')
firebase_url = os.getenv('FIREBASE_URL')
gemini_key = os.getenv('GEMINI_API_KEY')


# 簡體到繁體
# ------------------------------------------
from opencc import OpenCC
cc = OpenCC('s2t')  

def convert_to_traditional(simplified_text):
    return cc.convert(simplified_text)
# ------------------------------------------

# 自動檢測語言並翻譯成繁体中文
# ------------------------------------------
from googletrans import Translator, LANGUAGES

translator = Translator()
def translate_to_traditional(text):
    translation = translator.translate(text, dest='zh-tw').text
    return translation
# ------------------------------------------

# Initialize the Gemini Pro API
genai.configure(api_key=gemini_key)

# --------------------------------
# from linebot.models import ImageMessage, MessageContent

def handle_image_message(event, line_bot_api):
    try:
        message_id = event['message']['id']
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = BytesIO()
        for chunk in message_content.iter_content():
            image_bytes.write(chunk)
        image_bytes.seek(0)

        print("Received image data, size:", image_bytes.getbuffer().nbytes)

        description = process_image_with_gemini(image_bytes.getvalue())

        if description:
            translated_description = translate_to_traditional(description)
            if translated_description:
                reply_msg = TextSendMessage(text=translated_description)
            else:
                reply_msg = TextSendMessage(text=description)
        else:
            reply_msg = TextSendMessage(text="未能生成描述")
        line_bot_api.reply_message(event['replyToken'], reply_msg)
    except Exception as e:
        print("Error processing image message:", str(e))
        reply_msg = TextSendMessage(text="處理圖片時發生錯誤")
        line_bot_api.reply_message(event['replyToken'], reply_msg)


def process_image_with_gemini(image_bytes):
    try:
        encoded_image = base64.b64encode(image_bytes).decode('utf-8')

        request_data = {
            'parts': [
                {
                    'mime_type': 'image/jpeg',  # 根据你的圖片實際類型修改，例如'image/png'
                    'data': encoded_image,
                }
            ]
        }

        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        response = model.generate_content(request_data)

        # 日誌輸出：確認 API 響應
        print("API response received:", response.text if response else "No response")

        if response:
            return response.text
        else:
            return "無法生成圖片描述"
    except Exception as e:
        # 日誌輸出：處理失敗情况
        print("Error in Gemini API call:", str(e))
        return None

    # model = genai.GenerativeModel('gemini-pro-vision')
    # response = model.generate_content({
    #     'inputs': [
    #         {'data': base64.b64encode(image_bytes).decode('utf-8'), 'type': 'image'}
    #     ]
    # })
    # if response:
    #     return response.text
    # return "無法生成圖片描述"
# --------------------------------

# 縮短網址
def shorten_url(long_url):
    api_key = '4070ff49d794e63219553b663c974755ecd6b432989c04df8a38b58d65165567c4f5d6'
    headers = {
        'Content-Type': 'application/json',
        'reurl-api-key': api_key
    }
    data = {
        "url": long_url
    }
    response = requests.post('https://api.reurl.cc/shorten', json=data, headers=headers)
    if response.status_code == 200:
        return response.json()['short_url']
    else:
        return long_url  # 如果縮短失敗，返回原始 URL

# google新聞
def fetch_google_news():
    url = "https://news.google.com/home?hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        news_items = soup.find_all('a', class_='gPFEn')
        news_list = ["---以下是今日的熱門新聞---"]
        for item in news_items:
            title = item.text.strip()
            link = item['href']
            if link.startswith('.'):
                news_link = 'https://news.google.com' + link[1:]
            else:
                news_link = link
            short_news_link = shorten_url(news_link)  # 使用 shorten_url 函數縮短 URL
            news_list.append(f"{title}\n{short_news_link}")
        return "\n\n".join(news_list)
    else:
        return "Failed to retrieve news"


# 天氣預報
def get_weather_forecast():
    url = "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/F-C0032-017?Authorization=CWA-6D10CFFD-9032-4306-A043-865F79972F08&downloadType=WEB&format=JSON"
    response = requests.get(url)
    data = response.json()
    
    try:
        weather_forecast = data["cwaopendata"]["dataset"]["parameterSet"]["parameter"]

        selected_forecast = [weather_forecast[i] for i in [0, 1, 3]]
        second_param_value = weather_forecast[2]["parameterValue"].split("；")[0]
        selected_forecast.insert(1, { "parameterValue": second_param_value })

        formatted_forecast_with_newlines = [param["parameterValue"] for param in selected_forecast]
        final_forecast_text = "\n\n".join(formatted_forecast_with_newlines)
        return final_forecast_text
    except KeyError as e:
        print(f"Key error: {e} - Check the JSON path.")
        return "無法獲取天氣預報，請稍後嘗試。"

# 空氣品質
def get_air_quality_data(sitename):
    url = "https://data.moenv.gov.tw/api/v2/aqx_p_432?api_key=e8dd42e6-9b8b-43f8-991e-b3dee723a52d&limit=1000&sort=ImportDate%20desc&format=JSON"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        records = data.get('records', [])
        for record in records:
            if record.get('sitename') == sitename:
                county = record.get('county', 'N/A')
                aqi = record.get('aqi', 'N/A')
                status = record.get('status', 'N/A')
                pm25 = record.get('pm2.5', 'N/A')
                return f"縣市: {county}\n區域: {sitename}\n狀態: {status}\nAQI: {aqi}\nPM2.5: {pm25}"
        return f"找不到{sitename}的空氣品質資料"
    return "無法取得空氣品質資料，請稍後再試"

def process_user_input(user_input):
    sitename = user_input.replace("空氣品質", "").strip()
    return sitename


# 查詢農民曆
def fetch_peasant_calendar():
    url = 'https://www.bestday123.com/'
    try:
        response = requests.get(url)
        if response.status_code == 200:
            html = response.content
            soup = BeautifulSoup(html, 'html.parser')

            # 定位到包含黃道吉日資訊的主要區塊
            calendar_div = soup.find('div', style='width: 500px;')
            if calendar_div:
                calendar_data = calendar_div.find_all('td')
                if calendar_data:
                    peasant_calendar = []
                    for item in calendar_data:
                        peasant_calendar.append(item.text.strip())

                    # 格式化資訊
                    formatted_calendar = '\n'.join(peasant_calendar)
                    return formatted_calendar
                else:
                    return "找不到黃道吉日資訊"
            else:
                return "找不到主要區塊"
        else:
            return f"無法取得網頁內容。狀態碼：{response.status_code}"
    except Exception as e:
        print(f"Error fetching peasant calendar: {str(e)}")
        return "無法獲取黃道吉日資訊，請稍後再試。"

# --------------------------------
#查詢天氣
def get_weather_by_city(city_name, district_name):
    city_name_encoded = requests.utils.quote(city_name)
    district_name_encoded = requests.utils.quote(district_name)
    url = f"https://weather.yam.com/{district_name_encoded}/{city_name_encoded}"

    response = requests.get(url)

    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        today_weather = soup.find('div', class_='today')

        if today_weather:
            date_area = today_weather.find('div', class_='dateArea')
            day_of_week = date_area.find('h3').text.strip()
            date = date_area.find('div', class_='day').text.strip()

            temp_area = today_weather.find('div', class_='tempB')
            temperature = temp_area.text.strip()

            detail_area = today_weather.find('div', class_='detail')
            if detail_area:
                details = detail_area.find_all('p')
                feels_like = details[0].text.strip().split(':')[1].strip()
                rain_chance = details[1].text.strip().split(':')[1].strip()
                humidity = details[2].text.strip().split(':')[1].strip()
                uv_index = details[3].text.strip().split(':')[1].strip()
                air_quality = details[4].text.strip().split(':')[1].strip()
                wind_speed = details[5].text.strip().split(':')[1].strip()

                weather_info = (
                    f"{city_name} {district_name} 天氣資訊 ({day_of_week} {date})\n"
                    f"溫度: {temperature}\n"
                    f"體感溫度: {feels_like}\n"
                    f"降雨機率: {rain_chance}\n"
                    f"相對濕度: {humidity}\n"
                    f"紫外線指數: {uv_index}\n"
                    f"空氣品質: {air_quality}\n"
                    f"風速: {wind_speed}"
                )
                return weather_info
            else:
                return "找不到詳細天氣資訊，請稍後再試。"
        else:
            return "找不到天氣資訊，請稍後再試。"
    else:
        return "無法取得天氣資訊，請稍後再試。"

def parse_user_input(user_input):
    # 使用正規表達式來判斷是否符合「高雄左營天氣」的簡化格式
    match = re.match(r'^(.{2})(.{2})(天氣)$', user_input)
    if match:
        city_name = match.group(1)
        district_name = match.group(2) + '區'
    else:
        return None, None

    return city_name, district_name
# --------------------------------


def linebot(request):

    body = request.get_data(as_text=True)
    json_data = json.loads(body)

    try:
        line_bot_api = LineBotApi(token)
        handler = WebhookHandler(secret)
        signature = request.headers['X-Line-Signature']
        handler.handle(body, signature)
        event = json_data['events'][0]
        tk = event['replyToken']
        user_id = event['source']['userId']
        msg_type = event['message']['type']

        fdb = firebase.FirebaseApplication(firebase_url, None)
        user_chat_path = f'chat/{user_id}'
        chat_state_path = f'state/{user_id}'
        chatgpt = fdb.get(user_chat_path, None)

        if msg_type == 'text':
            msg = event['message']['text']

            if chatgpt is None:
                messages = []
            else:
                messages = chatgpt
            if msg == '!清空' or msg == '！清空':
                reply_msg = TextSendMessage(text='對話歷史紀錄已經清空！')
                fdb.delete(user_chat_path, None)
            elif "農曆" in msg:
                calendar_message = fetch_peasant_calendar()
                reply_msg = TextSendMessage(text=calendar_message)
            elif msg == '雷達回波圖':
                # 回傳雷達回波圖
                image_url = "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Observation/O-A0058-001.png"
                reply_msg = ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
            elif msg == '溫度分布圖':
                image_url = "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Observation/O-A0038-001.jpg"
                reply_msg = ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
            elif msg == '天氣資訊':
                forecast_message = get_weather_forecast()
                reply_msg = TextSendMessage(text=forecast_message)
            elif msg == '新聞':
                news_message = fetch_google_news()
                reply_msg = TextSendMessage(text=news_message)
            elif "空氣品質" in msg:
                msg_after = process_user_input(msg)
                air_quality_message = get_air_quality_data(msg_after)
                reply_msg = TextSendMessage(text=air_quality_message)
            elif msg == '使用說明':
                pass
            elif '天氣' in msg:
                msg = msg.strip()
                # 嘗試使用簡化格式來解析
                city_name, district_name = parse_user_input(msg)

                # 如果使用者輸入包含「天氣」，則去除最後的兩個字元
                if msg.endswith("天氣"):
                    msg = msg[:-2]

                if not city_name or not district_name:
                    # 如果無法解析為簡化格式，則使用原有方式處理
                    if "市" in msg:
                        city_name, district_name = msg.split("市")
                        city_name += "市"
                    else:
                        district_name = msg
                        
                if city_name and district_name:
                    forecast_message = get_weather_by_city(city_name, district_name)
                    if forecast_message:
                        reply_msg = TextSendMessage(text=forecast_message)
                    else:
                        reply_msg = TextSendMessage(text="無法取得天氣資訊，請稍後再試。")
                else:
                    reply_msg = TextSendMessage(text="請輸入完整的資訊，例如：高雄市左營區天氣")
            else:
                model = genai.GenerativeModel('gemini-1.5-flash-latest')
                messages.append({'role':'user','parts': [msg]})
                response = model.generate_content(messages)
                traditional_response = translate_to_traditional(response.text)  # 轉換成繁體中文
                messages.append({'role':'model','parts': [traditional_response]})
                reply_msg = TextSendMessage(text=traditional_response)
                # 更新firebase中的對話紀錄
                fdb.put_async(user_chat_path, None, messages)

            line_bot_api.reply_message(tk, reply_msg)

        elif msg_type == 'image':
            handle_image_message(event, line_bot_api)

        elif msg_type == 'sticker':
            sticker_id = event['message']['stickerId']
            package_id = event['message']['packageId']
            reply_msg = StickerSendMessage(package_id=package_id, sticker_id=sticker_id)
            line_bot_api.reply_message(tk, reply_msg)
            
    except Exception as e:
        detail = e.args[0]
        print(detail)
    return 'OK'

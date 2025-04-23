import subprocess
import sys

# Tự động cài đặt các package trong requirements.txt nếu thiếu
def install_requirements():
    try:
        import pkg_resources
        with open('requirements.txt', 'r') as f:
            packages = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        installed = {pkg.key for pkg in pkg_resources.working_set}
        missing = [pkg for pkg in packages if pkg.lower() not in installed]
        if missing:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', *missing])
    except Exception:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])

install_requirements()

from flask import Flask, render_template, request, send_file, jsonify
import base64
import pandas as pd
import os
import io
import requests
import threading
import re

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Simple in-memory progress tracking
task_progress = {}

def call_gemini_api(api_key, model, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        # Extract text from response (adjust if Gemini API changes)
        return result['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"[ERROR] {str(e)}"

def has_multiple_pronouns(text):
    """Kiểm tra nếu câu chứa nhiều xưng hô không tự nhiên như bạn/em/chị cùng lúc."""
    pronouns = ["bạn", "em", "chị", "anh", "cô", "chú", "bác", "ông", "bà", "con", "cháu"]
    found = [p for p in pronouns if p in text.lower()]
    return len(found) > 1

def call_gemini_score_api(api_key, model, content, ctype):
    """Gửi nội dung lên Gemini để chấm điểm chất lượng (1-10) cho từng thể loại."""
    # Luôn dùng model riêng cho chấm điểm
    score_model = "gemini-2.5-flash-preview-04-17"
    pronoun_criteria = "Không sử dụng nhiều xưng hô trong cùng một câu (ví dụ: bạn/em/chị), chỉ chọn một xưng hô phù hợp hoặc dùng từ trung tính."
    if ctype == 'Rap':
        score_prompt = (
            f"Hãy chấm điểm chất lượng đoạn rap sau trên thang điểm 10 (1 là tệ nhất, 10 là xuất sắc). "
            "Tiêu chí: ngôn ngữ trẻ trung, sáng tạo, vần điệu tốt, flow cuốn hút, có điểm nhấn, cảm xúc rõ ràng, đa dạng ý tưởng, emoji đầu dòng phải thật sáng tạo, giữ, độc đáo, không lặp lại, tự nhiên, phù hợp văn hóa Việt Nam, không phản cảm. "
            "Đặc biệt: Nội dung phải đọc có vần điệu, không bị sượng, không ép vần thiếu tự nhiên, nghe như một đoạn rap thực sự. "
            f"{pronoun_criteria} "
            "Chỉ trả về duy nhất một số nguyên từ 1 đến 10, không giải thích.\n"
            f"Đoạn rap:\n{content}"
        )
    elif ctype == 'Wish':
        score_prompt = (
            f"Hãy chấm điểm chất lượng lời chúc sinh nhật sau trên thang điểm 10 (1 là tệ nhất, 10 là xuất sắc). "
            "Tiêu chí: ngắn gọn, súc tích, sáng tạo, dễ thương, ý nghĩa, truyền tải cảm hứng tích cực, đa dạng, ấm áp, tự nhiên, icon cảm xúc phù hợp, không phản cảm, phù hợp văn hóa Việt Nam. "
            f"{pronoun_criteria} "
            "Chỉ trả về duy nhất một số nguyên từ 1 đến 10, không giải thích.\n"
            f"Lời chúc:\n{content}"
        )
    elif ctype == 'Poem':
        score_prompt = (
            f"Hãy chấm điểm chất lượng bài thơ lục bát 4 câu sau trên thang điểm 10 (1 là tệ nhất, 10 là xuất sắc). "
            "Tiêu chí: đúng thể thơ lục bát 4 câu (6-8-6-8 chữ), sáng tạo, truyền cảm xúc, ý nghĩa, không lặp lại nguyên văn Tagline/Prompt, đa dạng ý tưởng, tự nhiên, không phản cảm, phù hợp văn hóa Việt Nam. "
            "Đặc biệt: Nội dung phải đọc có vần điệu, không bị sượng, không ép vần thiếu tự nhiên, nghe như một bài thơ thực sự. "
            f"{pronoun_criteria} "
            "Chỉ trả về duy nhất một số nguyên từ 1 đến 10, không giải thích.\n"
            f"Bài thơ:\n{content}"
        )
    else:
        score_prompt = (
            f"Hãy chấm điểm chất lượng nội dung sau trên thang điểm 10 (1 là tệ nhất, 10 là xuất sắc). "
            "Tiêu chí: sáng tạo, truyền cảm xúc, ý nghĩa, đa dạng, tự nhiên, không phản cảm, phù hợp văn hóa Việt Nam. "
            f"{pronoun_criteria} "
            "Chỉ trả về duy nhất một số nguyên từ 1 đến 10, không giải thích.\n"
            f"Nội dung:\n{content}"
        )
    score_text = call_gemini_api(api_key, score_model, score_prompt)
    match = re.search(r'\b([1-9]|10)\b', str(score_text))
    if match:
        return int(match.group(1))
    return None

def generate_content_background(df, api_key, model, content_types, num_variations, output_format, task_id, event=None):
    results = []
    total = len(df) * len(content_types) * num_variations
    current = 0
    if task_id not in task_progress:
        task_progress[task_id] = {'current': 0, 'total': total}
    for idx, row in df.iterrows():
        for ctype in content_types:
            intro = f"Tagline: '{row['Tagline']}'\nPrompt: '{row['Prompt']}'\n"
            # Thêm chủ đề event nếu có
            if event and event != '':
                event_map = {
                    'birthday': 'sinh nhật',
                    'mother_day': 'Mother Day',
                    'women_day': 'Women Day',
                    'phu_nu_vn': 'Phụ nữ Việt Nam',
                    'teacher_day': 'Ngày nhà giáo Việt Nam',
                    'valentine': 'Ngày lễ tình nhân',
                    'mid_autumn': 'Tết trung thu',
                    'tet_nguyen_dan': 'Tết Nguyên Đán',
                    'new_year': 'Tết Dương Lịch'
                }
                event_name = event_map.get(event, event)
                intro += f"Chủ đề: {event_name}\n"
            if ctype == 'Poem':
                prompt = (
                    f"{intro}Hãy sáng tạo và viết {num_variations} bài thơ lục bát, mỗi bài gồm đúng 4 câu, theo thể thơ lục bát: câu 1 và 3 đúng 6 chữ, câu 2 và 4 đúng 8 chữ. "
                    "YÊU CẦU: Mỗi bài thơ phải xuống dòng rõ ràng (mỗi câu 1 dòng), mỗi bài cách nhau bằng 2 dòng trống. "
                    "Hạn chế tối đa việc lặp lại nguyên văn bất kỳ câu nào trong Tagline hoặc Prompt vào bài thơ. Chỉ nên biến tấu, truyền tải cảm xúc, ý nghĩa, phong cách, chất riêng của Tagline và Prompt, không copy lại từ gốc. "
                    "ƯU TIÊN: Ý tưởng mới lạ, hình ảnh ẩn dụ, liên tưởng độc đáo, cảm xúc mạnh, phá cách, bất ngờ, không lối mòn. Hãy tưởng tượng như một nhà thơ chuyên nghiệp tạo ra phong cách riêng cho từng bài. "
                    "Chỉ trả về các bài thơ mà từng câu đúng số chữ (6 hoặc 8), nếu không đúng thì loại bỏ bài đó, không trả về. "
                    "Tuyệt đối không thêm giải thích, không thêm tiêu đề, không đánh số thứ tự. "
                    "Dưới đây là ví dụ đúng thể thơ lục bát 4 câu:\n"
                    "Mừng ngày sinh nhật hồng tươi\nBạn bè sum họp đủ mười tám đôi\nNến hồng lung linh sáng ngời\nChúc cho tuổi mới rạng ngời niềm vui.\n\n"
                    "Gió xuân khe khẽ bên thềm\nChúc cho tuổi mới êm đềm an nhiên\nHoa tươi khoe sắc vườn tiên\nMong cho hạnh phúc nối liền tháng năm.\n\n"
                    f"Chỉ trả về danh sách tối đa {num_variations} bài thơ, mỗi bài đúng 4 dòng, mỗi bài cách nhau 2 dòng trống. "
                    "Tuyệt đối không sử dụng từ ngữ tục tĩu, bạo lực, phản cảm, hoặc xưng hô thiếu lịch sự (ví dụ: mày, tao, ...). Chỉ dùng ngôn ngữ lịch sự, phù hợp văn hóa Việt Nam."
                )
            elif ctype == 'Rap':
                prompt = (
                    f"{intro}Hãy sáng tạo và viết {num_variations} đoạn rap riêng biệt, mỗi đoạn gồm đúng 2 câu (mỗi câu một dòng), thể hiện rõ 'chất' rap.\n"
                    "YÊU CẦU:\n"
                    "1. Ngôn ngữ trẻ trung, có vần điệu tốt, flow cuốn hút, có thể có điểm nhấn (punchline) ấn tượng.\n"
                    "2. Truyền tải đúng tinh thần, cảm xúc, ý nghĩa của Tagline và Prompt.\n"
                    "3. Các đoạn rap phải thật sự khác biệt về flow, cấu trúc, ý tưởng, hình ảnh, không lặp lại lối mòn, không nhàm chán.\n"
                    "4. ƯU TIÊN: Sáng tạo, phá cách, bất ngờ, dùng hình ảnh liên tưởng, ẩn dụ, punchline độc đáo, phong cách riêng biệt. Hãy tưởng tượng như một rapper chuyên nghiệp tạo ra mỗi đoạn là một màu sắc riêng.\n"
                    "5. Mỗi đoạn rap gồm đúng 2 câu. Trình bày mỗi câu trên một dòng riêng biệt.\n"
                    "6. Mỗi câu PHẢI bắt đầu bằng một hoặc hai emoji (icon) liên quan đến âm nhạc, tiệc tùng, sinh nhật, cảm xúc, v.v. (ví dụ: 🎤, 🎶, 🎵, 🎧, 🥳, 🎂, 🎸, 🎺, 🎷, 🕺, 💃, 🔥, ✨, 😎, 😍, v.v.). Ưu tiên các emoji nhiều màu sắc, sáng tạo, không lặp lại giữa các câu, có thể kết hợp 2 emoji đầu dòng để thêm phần sinh động.\n"
                    "7. Không gộp 2 câu vào một dòng.\n"
                    "8. Không trả về đoạn rap chỉ có 1 câu.\n"
                    "9. Toàn bộ đoạn rap (2 dòng) không vượt quá 120 ký tự.\n"
                    "10. Đảm bảo chất lượng cao, nghe tự nhiên, phù hợp văn hóa Việt Nam.\n"
                    f"Chỉ trả về đúng {num_variations} đoạn rap theo yêu cầu. Các đoạn rap (mỗi đoạn gồm 2 dòng) phải cách nhau bằng 1 dòng trống. Tuyệt đối không thêm giải thích, tiêu đề, hay đánh số thứ tự. "
                    "Tuyệt đối không sử dụng từ ngữ tục tĩu, bạo lực, phản cảm, hoặc xưng hô thiếu lịch sự (ví dụ: mày, tao, ...). Chỉ dùng ngôn ngữ lịch sự, phù hợp văn hóa Việt Nam."
                )
            elif ctype == 'Wish':
                prompt = (
                    f"{intro}Hãy sáng tạo và viết {num_variations} lời chúc sinh nhật riêng biệt, dựa trên Tagline và Prompt.\n"
                    "YÊU CẦU:\n"
                    "1. Mỗi lời chúc cần ngắn gọn, súc tích (không vượt quá 25 từ), nhưng vẫn truyền tải được ý nghĩa, sự chân thành và cảm hứng.\n"
                    "2. Lời chúc cần ấm áp, tự nhiên, phù hợp với không khí sinh nhật vui vẻ.\n"
                    "3. Các lời chúc phải thật sự đa dạng, khác biệt nhau về cách mở đầu, cấu trúc câu, hình ảnh, ý tưởng, không lặp lại lối mòn, không nhàm chán.\n"
                    "4. ƯU TIÊN: Sáng tạo, bất ngờ, dùng hình ảnh liên tưởng, ẩn dụ, cảm xúc mạnh, phong cách riêng biệt. Hãy tưởng tượng như một người viết lời chúc chuyên nghiệp tạo ra mỗi lời chúc là một màu sắc riêng.\n"
                    "5. Có thể thêm 1-2 icon cảm xúc phù hợp cuối mỗi lời chúc để sinh động hơn (không bắt buộc, không dùng quá nhiều hay không liên quan).\n"
                    "6. Đảm bảo chất lượng cao, câu văn mượt mà, phù hợp văn hóa Việt Nam.\n"
                    f"Chỉ trả về đúng {num_variations} lời chúc theo yêu cầu, mỗi lời chúc cách nhau bằng 1 dòng trống. Tuyệt đối không thêm giải thích, tiêu đề, hay đánh số thứ tự. "
                    "Tuyệt đối không sử dụng từ ngữ tục tĩu, bạo lực, phản cảm, hoặc xưng hô thiếu lịch sự (ví dụ: mày, tao, ...). Chỉ dùng ngôn ngữ lịch sự, phù hợp văn hóa Việt Nam."
                )
            else:
                prompt = (
                    f"{intro}Hãy sáng tạo và viết {num_variations} biến thể khác nhau cho nội dung theo thể loại [{ctype}]. "
                    "Mỗi biến thể phải truyền tải cảm xúc, ý nghĩa của Tagline và Prompt trên, nhưng không lặp lại nguyên văn Tagline hoặc Prompt trong từng biến thể. "
                    "Các biến thể cần đa dạng về giọng điệu, cấu trúc, sáng tạo, chất lượng cao, phù hợp với mọi lứa tuổi, không chứa yếu tố bạo lực, phản cảm, phản động. "
                    "ƯU TIÊN: Sáng tạo, bất ngờ, hình ảnh liên tưởng, ẩn dụ, cảm xúc mạnh, phong cách riêng biệt, không lặp lại lối mòn.\n"
                    f"Chỉ trả về danh sách {num_variations} biến thể đó, mỗi biến thể trên một dòng hoặc ngăn cách rõ ràng. "
                    "Tuyệt đối không sử dụng từ ngữ tục tĩu, bạo lực, phản cảm, hoặc xưng hô thiếu lịch sự (ví dụ: mày, tao, ...). Chỉ dùng ngôn ngữ lịch sự, phù hợp văn hóa Việt Nam."
                )

            max_retry = 1000
            all_variations = []
            tried_texts = set()
            for attempt in range(max_retry):
                prev_count = len(all_variations)
                result = call_gemini_api(api_key, model, prompt)
                if ctype == 'Rap':
                    rap_pairs = []
                    temp = []
                    for line in result.split('\n'):
                        if line.strip():
                            temp.append(line.strip())
                            if len(temp) == 2:
                                rap = '\n'.join(temp)
                                # Kiểm tra độ dài đoạn rap (<=120 ký tự)
                                if rap not in tried_texts and len(rap) <= 120:
                                    rap_pairs.append(rap)
                                    tried_texts.add(rap)
                                temp = []
                    all_variations.extend([v for v in rap_pairs if v not in all_variations])
                elif ctype == 'Poem':
                    poems = []
                    poem_lines = []
                    for line in result.split('\n'):
                        if line.strip() == '':
                            if poem_lines:
                                if len(poem_lines) == 4:
                                    poem = '\n'.join(poem_lines)
                                    if poem not in tried_texts:
                                        poems.append(poem)
                                        tried_texts.add(poem)
                                poem_lines = []
                        else:
                            poem_lines.append(line.strip())
                            if len(poem_lines) == 4:
                                poem = '\n'.join(poem_lines)
                                if poem not in tried_texts:
                                    poems.append(poem)
                                poem_lines = []
                    if poem_lines and len(poem_lines) == 4:
                        poem = '\n'.join(poem_lines)
                        if poem not in tried_texts:
                            poems.append(poem)
                            tried_texts.add(poem)
                    poems = [p for p in poems if is_luc_bat_4c(p)]
                    all_variations.extend([v for v in poems if v not in all_variations])
                elif ctype == 'Wish':
                    if isinstance(result, str):
                        wish_lines = [v.strip() for v in result.split('\n') if v.strip()]
                    else:
                        wish_lines = []
                    for wish in wish_lines:
                        if wish not in tried_texts:
                            all_variations.append(wish)
                            tried_texts.add(wish)
                else:
                    if isinstance(result, str):
                        lines = [v.strip() for v in result.split('\n') if v.strip()]
                    else:
                        lines = []
                    for line in lines:
                        if line not in tried_texts:
                            all_variations.append(line)
                            tried_texts.add(line)
                # Nếu không có biến thể mới nào được thêm vào, dừng vòng lặp để tránh lặp vô hạn
                if len(all_variations) == prev_count:
                    break
                if ctype == 'Rap' and len(all_variations) >= num_variations:
                    break
            # Nếu sau max_retry vẫn chưa đủ, hỏi user có muốn tiếp tục hay skip
            if len(all_variations) < num_variations:
                task_progress[task_id] = {
                    'current': current,
                    'total': total,
                    'waiting_user': True,
                    'row_idx': idx,
                    'ctype': ctype,
                    'row': row.to_dict(),
                    'num_variations': num_variations,
                    'output_format': output_format,
                    'results': results
                }
                return  # Dừng lại để chờ quyết định user
            variations = all_variations[:num_variations]
            # Ghi đủ num_variations dòng cho mỗi loại, nếu thiếu thì tiếp tục sinh bù cho đến khi đủ hoặc hết max_retry
            i = 0
            retry_count = 0
            max_retry_bu = 1000
            valid_variations = []
            # Lọc các biến thể hợp lệ ban đầu
            for v in all_variations:
                if ctype == 'Wish':
                    if has_multiple_pronouns(v) or count_words(v) > 25:
                        continue
                valid_variations.append(v)
            # Nếu chưa đủ, tiếp tục sinh bù (chỉ cho Wish: kiểm tra cả xưng hô và số từ)
            while len(valid_variations) < num_variations and retry_count < max_retry_bu:
                result = call_gemini_api(api_key, model, prompt)
                new_variations = []
                if ctype == 'Rap':
                    rap_pairs = []
                    temp = []
                    for line in result.split('\n'):
                        if line.strip():
                            temp.append(line.strip())
                            if len(temp) == 2:
                                rap = '\n'.join(temp)
                                # Kiểm tra độ dài đoạn rap (<=120 ký tự)
                                if rap not in valid_variations and len(rap) <= 120:
                                    rap_pairs.append(rap)
                                temp = []
                    new_variations = rap_pairs
                elif ctype == 'Poem':
                    poems = []
                    poem_lines = []
                    for line in result.split('\n'):
                        if line.strip() == '':
                            if poem_lines:
                                if len(poem_lines) == 4:
                                    poem = '\n'.join(poem_lines)
                                    if poem not in valid_variations:
                                        poems.append(poem)
                                poem_lines = []
                        else:
                            poem_lines.append(line.strip())
                            if len(poem_lines) == 4:
                                poem = '\n'.join(poem_lines)
                                if poem not in valid_variations:
                                    poems.append(poem)
                                poem_lines = []
                    if poem_lines and len(poem_lines) == 4:
                        poem = '\n'.join(poem_lines)
                        if poem not in valid_variations:
                            poems.append(poem)
                    poems = [p for p in poems if is_luc_bat_4c(p)]
                    new_variations = poems
                elif ctype == 'Wish':
                    if isinstance(result, str):
                        wish_lines = [v.strip() for v in result.split('\n') if v.strip()]
                    else:
                        wish_lines = []
                    for wish in wish_lines:
                        if not has_multiple_pronouns(wish) and count_words(wish) <= 25 and wish not in valid_variations:
                            new_variations.append(wish)
                else:
                    if isinstance(result, str):
                        lines = [v.strip() for v in result.split('\n') if v.strip()]
                    else:
                        lines = []
                    for line in lines:
                        if line not in valid_variations:
                            new_variations.append(line)
                valid_variations.extend([v for v in new_variations if v not in valid_variations])
                retry_count += 1
            # Ghi đúng num_variations dòng cho mỗi loại
            for i in range(num_variations):
                if i < len(valid_variations):
                    content = valid_variations[i]
                    point = call_gemini_score_api(api_key, model, content, ctype)
                    results.append({
                        'Tagline': row['Tagline'],
                        'Prompt': row['Prompt'],
                        'Content_Type': ctype,
                        'Variation_Index': i+1,
                        'Content': content,
                        'Point': point
                    })
                else:
                    results.append({
                        'Tagline': row['Tagline'],
                        'Prompt': row['Prompt'],
                        'Content_Type': ctype,
                        'Variation_Index': i+1,
                        'Content': 'Không sinh được biến thể hợp lệ',
                        'Point': None
                    })
                current += 1
                task_progress[task_id]['current'] = current
                task_progress[task_id]['total'] = total
    # Đảm bảo tên file output là {task_id}.csv/xlsx, không có prefix "result_"
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], f"{task_id}.csv")
    if output_format == 'xlsx':
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], f"{task_id}.xlsx")
        df_result = pd.DataFrame(results)
        df_result.to_excel(output_path, index=False)
        task_progress[task_id]['output_xlsx'] = output_path
    else:
        df_result = pd.DataFrame(results)
        df_result.to_csv(output_path, index=False)
        task_progress[task_id]['output'] = output_path
    task_progress[task_id]['done'] = True
    print(f"[DONE] Task {task_id} đã ghi file: {output_path}")

def count_words(text):
    return len([w for w in text.split() if w.strip()])

def is_luc_bat_4c(poem: str) -> bool:
    """Kiểm tra 1 bài thơ 4 câu có đúng thể lục bát 6-8-6-8 chữ không."""
    lines = [line.strip() for line in poem.split('\n') if line.strip()]
    if len(lines) != 4:
        return False
    return count_words(lines[0]) == 6 and count_words(lines[1]) == 8 and count_words(lines[2]) == 6 and count_words(lines[3]) == 8

@app.route('/', methods=['GET'])
def index():
    # Danh sách các event để truyền sang template
    events = [
        ('birthday', 'Sinh nhật'),
        ('mother_day', 'Mother Day'),
        ('women_day', 'Women Day'),
        ('phu_nu_vn', 'Phụ nữ Việt Nam'),
        ('teacher_day', 'Ngày nhà giáo Việt Nam'),
        ('valentine', 'Ngày lễ tình nhân'),
        ('mid_autumn', 'Tết trung thu'),
        ('tet_nguyen_dan', 'Tết Nguyên Đán'),
        ('new_year', 'Tết Dương Lịch')
    ]
    return render_template('index.html', events=events)

@app.route('/process', methods=['POST'])
def process():
    file = request.files.get('csv_file')
    api_key = request.form.get('api_key')
    model = request.form.get('model')
    content_types = request.form.getlist('content_types')
    task_id = request.form.get('task_id')
    output_format = request.form.get('output_format', 'csv')
    if not file or not api_key or not model or not content_types:
        return jsonify({'error': 'Thiếu thông tin đầu vào!'}), 400
    try:
        df = pd.read_csv(file)
        df.columns = [c.strip().replace('\u200b', '').replace('\xa0', '').replace('\ufeff', '') for c in df.columns]
    except Exception:
        return jsonify({'error': 'File CSV không hợp lệ!'}), 400
    if not set(['Tagline', 'Prompt']).issubset(df.columns):
        return jsonify({'error': 'File CSV phải có cột Tagline và Prompt!'}), 400
    num_variations = int(request.form.get('num_variations', 10))
    event = request.form.get('event')
    # Khởi tạo tiến trình 0 để frontend hiển thị 0%
    task_progress[task_id] = {'current': 0, 'total': len(df) * len(content_types) * num_variations}
    # Chạy sinh dữ liệu ở thread nền
    thread = threading.Thread(target=generate_content_background, args=(df, api_key, model, content_types, num_variations, output_format, task_id, event))
    thread.start()
    return jsonify({'success': True})

@app.route('/progress/<task_id>')
def progress(task_id):
    return jsonify(task_progress.get(task_id, {}))

@app.route('/download/<task_id>')
def download(task_id):
    info = task_progress.get(task_id)
    if not info or 'output' not in info:
        return 'Không tìm thấy file kết quả!', 404
    file_path = info['output']
    if not os.path.exists(file_path):
        app.logger.error(f"File không tồn tại: {file_path}")
        return 'File kết quả không tồn tại trên server!', 404
    try:
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        app.logger.error(f"Lỗi khi gửi file: {e}")
        return f'Lỗi khi gửi file: {str(e)}', 500

@app.route('/download_xlsx/<task_id>')
def download_xlsx(task_id):
    info = task_progress.get(task_id)
    if not info or 'output_xlsx' not in info:
        return 'Không tìm thấy file kết quả XLSX!', 404
    xlsx_path = info['output_xlsx']
    if not os.path.exists(xlsx_path):
        app.logger.error(f"File XLSX không tồn tại: {xlsx_path}")
        return 'File XLSX không tồn tại trên server!', 404
    try:
        return send_file(xlsx_path, as_attachment=True)
    except Exception as e:
        app.logger.error(f"Lỗi khi gửi file XLSX: {e}")
        return f'Lỗi khi gửi file XLSX: {str(e)}', 500

@app.route('/user_decision', methods=['POST'])
def user_decision():
    data = request.json
    task_id = data.get('task_id')
    decision = data.get('decision')  # 'retry' hoặc 'skip'
    info = task_progress.get(task_id)
    if not info or not info.get('waiting_user'):
        return jsonify({'error': 'Không có tác vụ nào đang chờ quyết định!'}), 400
    idx = info['row_idx']
    ctype = info['ctype']
    row = info['row']
    num_variations = info['num_variations']
    output_format = info['output_format']
    results = info['results']
    api_key = info.get('api_key')
    model = info.get('model')
    content_types = info.get('content_types', [ctype])
    df = pd.DataFrame([row])
    # Nếu skip: ghi kết quả lỗi, tiếp tục xử lý các dòng tiếp theo
    if decision == 'skip':
        results.append({
            'Tagline': row['Tagline'],
            'Prompt': row['Prompt'],
            'Content_Type': ctype,
            'Variation_Index': 1,
            'Content': 'Không sinh được biến thể hợp lệ (user skip)',
            'Point': None
        })
        info['current'] = info.get('current', 0) + 1
        task_progress[task_id] = {'current': info['current'], 'total': info['total']}
        # Tiếp tục xử lý các dòng tiếp theo
        thread = threading.Thread(target=generate_content_background, args=(df, api_key, model, content_types, num_variations, output_format, task_id))
        thread.start()
        return jsonify({'success': True, 'skipped': True})
    elif decision == 'retry':
        # Tiếp tục thử lại cho dòng này
        thread = threading.Thread(target=generate_content_background, args=(df, api_key, model, content_types, num_variations, output_format, task_id))
        thread.start()
        return jsonify({'success': True, 'retrying': True})
    else:
        return jsonify({'error': 'Quyết định không hợp lệ!'}), 400

if __name__ == '__main__':
    app.run(debug=True)

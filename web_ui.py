import streamlit as st
import os
import re
import traceback
import subprocess
import gc
from PIL import Image
from imageio_ffmpeg import get_ffmpeg_exe

# --- [UI 디자인 세팅] ---
st.set_page_config(page_title="자동 영상 변환기 | Ai 돈나", page_icon="🎬", layout="centered")

hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
header {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

if st.query_params.get("vip") != "da":
    st.markdown("""
    <div style='text-align: center; padding: 50px; margin-top: 50px;'>
        <h2 style='color: #E24A4A;'>🚨 접근이 차단되었습니다.</h2>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

st.markdown("""
<div style="text-align: center;">
    <h1 style="margin-bottom: 5px;">🎬 디에이 아카데미</h1>
    <h1 style="margin-top: 0px; color: #4A90E2;">자동 영상 변환기</h1>
    <p style="margin-top: 20px; font-size: 16px;">
        <strong>Ai 돈나의 원클릭 AI 스튜디오에 오신 것을 환영합니다!</strong>
    </p>
</div>
""", unsafe_allow_html=True)
st.divider()

def clean_text(text):
    return re.sub(r'[^가-힣a-zA-Z0-9]', '', text)

def parse_time(time_str):
    h, m, s_ms = time_str.split(':')
    s, ms = s_ms.replace(',', '.').split('.')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

def extract_scenes_from_script(script_path):
    with open(script_path, 'r', encoding='utf-8') as f:
        content = f.read()
    scenes = []
    if "대사 내용:" in content:
        parts = content.split("대사 내용:")
        for part in parts[1:]:
            dialogue = re.split(r'(영문 프롬프트:|{장면|프롬프트|\[)', part)[0].strip()
            cleaned = clean_text(dialogue)
            if cleaned: scenes.append(cleaned)
    else:
        blocks = content.strip().split('\n\n')
        for block in blocks:
            cleaned = clean_text(block)
            if cleaned: scenes.append(cleaned)
    return scenes

def match_srt_to_scenes(srt_path, scenes):
    with open(srt_path, 'r', encoding='utf-8') as f:
        blocks = f.read().strip().split('\n\n')
    srt_data = []
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            times = lines[1].split(' --> ')
            start = parse_time(times[0])
            end = parse_time(times[1])
            text = clean_text("".join(lines[2:]))
            srt_data.append({'start': start, 'end': end, 'text': text})

    scene_timings = []
    srt_idx = 0
    total_srt = len(srt_data)
    for scene_text in scenes:
        if srt_idx >= total_srt: break
        start_time = srt_data[srt_idx]['start']
        accumulated_text = ""
        end_time = start_time
        while srt_idx < total_srt:
            current_diff = abs(len(scene_text) - len(accumulated_text))
            next_diff = abs(len(scene_text) - (len(accumulated_text) + len(srt_data[srt_idx]['text'])))
            if next_diff <= current_diff:
                accumulated_text += srt_data[srt_idx]['text']
                end_time = srt_data[srt_idx]['end']
                srt_idx += 1
            else: break
        scene_timings.append(end_time - start_time)
    return scene_timings

col1, col2 = st.columns(2)
with col1:
    audio_file = st.file_uploader("🎵 1. 음성 (.mp3)", type=['mp3'])
    script_file = st.file_uploader("📝 3. 대본 (.txt)", type=['txt'])
with col2:
    srt_file = st.file_uploader("💬 2. 자막 (.srt)", type=['srt'])
    image_files = st.file_uploader("📸 4. 이미지 (여러 장 가능)", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)

st.divider()

if st.button("🚀 자동 영상 변환 시작", use_container_width=True):
    if not (audio_file and srt_file and script_file and image_files):
        st.error("⚠️ 4가지 파일을 모두 업로드해 주세요!")
    else:
        try:
            status_text = st.empty()
            # [변경 완료] 고급스러운 1단계 멘트
            status_text.info("🔄 [1/4] AI가 파일 데이터를 분석하고 동기화를 준비하고 있습니다...")
            
            os.makedirs("temp_workspace", exist_ok=True)
            audio_path = os.path.join("temp_workspace", audio_file.name)
            with open(audio_path, "wb") as f: f.write(audio_file.getbuffer())
            srt_path = os.path.join("temp_workspace", srt_file.name)
            with open(srt_path, "wb") as f: f.write(srt_file.getbuffer())
            script_path = os.path.join("temp_workspace", script_file.name)
            with open(script_path, "wb") as f: f.write(script_file.getbuffer())
            
            def get_number(filename):
                numbers = re.findall(r'\d+', filename)
                return int(numbers[0]) if numbers else 0
            
            sorted_images = sorted(image_files, key=lambda x: get_number(x.name))
            
            scenes_text = extract_scenes_from_script(script_path)
            if not scenes_text: raise ValueError("대본 파일 오류")
            scene_durations = match_srt_to_scenes(srt_path, scenes_text)
            
            if len(sorted_images) < len(scene_durations):
                st.error(f"⚠️ 업로드 이미지({len(sorted_images)}장)가 대본 장면 수({len(scene_durations)}개)보다 부족합니다.")
            else:
                # [변경 완료] 짠돌이 모드 -> 해상도 최적화 작업으로 포장
                status_text.info("🖼️ [2/4] 업로드된 이미지의 해상도 및 규격을 고화질 영상에 맞게 최적화하는 중입니다...")
                
                first_img_bytes = sorted_images[0].getvalue()
                with open(os.path.join("temp_workspace", "temp_first.jpg"), "wb") as f: f.write(first_img_bytes)
                with Image.open(os.path.join("temp_workspace", "temp_first.jpg")) as img:
                    target_w, target_h = img.size
                    target_w, target_h = target_w - (target_w % 2), target_h - (target_h % 2)
                
                resized_paths = []
                for i, img_file in enumerate(sorted_images):
                    if i >= len(scene_durations): break 
                    
                    raw_path = os.path.join("temp_workspace", f"raw_{i}.jpg")
                    new_p = os.path.join("temp_workspace", f"resized_{i}.jpg")
                    
                    with open(raw_path, "wb") as f: f.write(img_file.getvalue())
                    
                    with Image.open(raw_path).convert("RGB") as pil_img:
                        pil_img = pil_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                        pil_img.save(new_p, quality=85) 
                    
                    os.remove(raw_path) 
                    resized_paths.append(new_p)
                    gc.collect() 

                # [변경 완료] 초경량 엔진 -> 고성능 렌더링 엔진으로 포장
                status_text.info("🎬 [3/4] 고성능 미디어 엔진을 가동하여 영상과 음성의 싱크를 조립하고 있습니다...")

                concat_file_path = os.path.join("temp_workspace", "concat_list.txt")
                with open(concat_file_path, "w", encoding="utf-8") as f:
                    for i, duration in enumerate(scene_durations):
                        f.write(f"file '{os.path.abspath(resized_paths[i])}'\n")
                        f.write(f"duration {duration}\n")
                    if resized_paths:
                        f.write(f"file '{os.path.abspath(resized_paths[-1])}'\n")

                output_path = os.path.join("temp_workspace", "완성본_영상.mp4")
                
                # [변경 완료] 렌더링 대기 안내 멘트 고급화
                with st.spinner(f"⏳ [4/4] 최종 영상을 추출하고 있습니다. (파일 용량에 따라 수 분이 소요될 수 있으니 창을 닫지 마세요)"):
                    ffmpeg_exe = get_ffmpeg_exe()
                    cmd = [
                        ffmpeg_exe, "-y",
                        "-f", "concat", "-safe", "0",
                        "-i", concat_file_path, "-i", audio_path,
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest",
                        output_path
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        raise RuntimeError(f"엔진 렌더링 오류: {result.stderr}")
                
                status_text.empty()
                st.success("🎉 렌더링 완료! 대본 싱크가 완벽하게 맞는 프리미엄 영상이 완성되었습니다!")
                st.balloons()
                
                with open(output_path, "rb") as file:
                    st.download_button("📥 완성된 영상 다운로드 하기", data=file, file_name="Ai돈나_자동완성_영상.mp4", mime="video/mp4", type="primary", use_container_width=True)
                    
        except Exception as e:
            st.error("🚨 서버 메모리 한계 초과 또는 파일 오류입니다.")
            st.warning("""
            **💡 [해결 방법]**
            1. **이미지 용량 줄이기:** 올리신 이미지 용량이 너무 큽니다. 'TinyPNG' 같은 사이트에서 용량을 압축한 뒤 올려주세요.
            2. **분량 쪼개기:** 영상을 절반으로 나누어서 렌더링해 주세요.
            새로고침(F5) 후 다시 시도해 주세요!
            """)
import streamlit as st
import os
import re
import traceback
import subprocess
from PIL import Image
from imageio_ffmpeg import get_ffmpeg_exe

# --- [UI 디자인 세팅] ---
st.set_page_config(page_title="자동 영상 변환기 | Ai 돈나", page_icon="🎬", layout="centered")

# --- [보안 1: 기본 UI 숨기기] ---
hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
header {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- [보안 2: VIP 자동 인증] ---
if st.query_params.get("vip") != "da":
    st.markdown("""
    <div style='text-align: center; padding: 50px; margin-top: 50px;'>
        <h2 style='color: #E24A4A;'>🚨 접근이 차단되었습니다.</h2>
        <p style='font-size: 16px; color: #555;'>
            본 프로그램은 디에이 아카데미 수강생 전용 프리미엄 도구입니다.<br>
            정규 강의실(라이브클래스)을 통해서만 정상적으로 접속하실 수 있습니다.
        </p>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# --- [UI 본문] ---
st.markdown("""
<div style="text-align: center;">
    <h1 style="margin-bottom: 5px;">🎬 디에이 아카데미</h1>
    <h1 style="margin-top: 0px; color: #4A90E2;">자동 영상 변환기</h1>
    <p style="margin-top: 20px; font-size: 16px;">
        <strong>Ai 돈나의 원클릭 AI 스튜디오에 오신 것을 환영합니다!</strong><br><br>
        아래에 4가지 파일(음성, 자막, 대본, 이미지)을 올려주시면<br>
        대본 싱크에 맞는 완벽한 롱폼 영상이 자동으로 완성됩니다.
    </p>
</div>
""", unsafe_allow_html=True)

st.divider()

# --- [기능 함수들] ---
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
            else:
                break
        scene_timings.append(end_time - start_time)
    return scene_timings

# --- [웹 파일 업로드 화면] ---
col1, col2 = st.columns(2)
with col1:
    audio_file = st.file_uploader("🎵 1. 음성 파일 업로드 (.mp3)", type=['mp3'])
    script_file = st.file_uploader("📝 3. 대본 파일 업로드 (.txt)", type=['txt'])
with col2:
    srt_file = st.file_uploader("💬 2. 자막 파일 업로드 (.srt)", type=['srt'])
    image_files = st.file_uploader("📸 4. 이미지 파일들 업로드 (여러 장 드래그 가능)", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)

st.divider()

# --- [실행 버튼 및 초경량 렌더링 로직] ---
st.write("") 
if st.button("🚀 자동 영상 변환 시작하기", use_container_width=True):
    if not (audio_file and srt_file and script_file and image_files):
        st.error("⚠️ 4가지 파일을 모두 업로드해 주세요!")
    else:
        try:
            st.write("") 
            status_text = st.empty()
            status_text.info("🔄 작업 준비 중... (파일을 분석하고 있습니다)")
            
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
            image_paths = []
            for img in sorted_images:
                img_path = os.path.join("temp_workspace", img.name)
                with open(img_path, "wb") as f: f.write(img.getbuffer())
                image_paths.append(img_path)
                
            scenes_text = extract_scenes_from_script(script_path)
            if not scenes_text:
                raise ValueError("대본 파일(.txt)에서 대사를 찾을 수 없습니다.")

            scene_durations = match_srt_to_scenes(srt_path, scenes_text)
            
            if len(image_paths) < len(scene_durations):
                st.error(f"⚠️ 경고: 업로드한 이미지 개수({len(image_paths)}장)가 대본 장면 수({len(scene_durations)}개)보다 부족합니다! 대본을 수정해 주세요.")
            else:
                # --- [초경량 엔진 가동 시작] ---
                status_text.info("🖼️ 이미지 규격을 통일하는 중입니다... (메모리 절약 모드)")
                
                # 1. FFmpeg 에러를 막기 위해 모든 이미지 크기를 첫 번째 이미지 크기에 맞춤 (짝수로)
                first_img = Image.open(image_paths[0]).convert("RGB")
                target_w, target_h = first_img.size
                target_w, target_h = target_w - (target_w % 2), target_h - (target_h % 2)
                
                resized_paths = []
                for p in image_paths:
                    img = Image.open(p).convert("RGB")
                    img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                    new_p = p + "_resized.jpg"
                    img.save(new_p, quality=95)
                    resized_paths.append(new_p)

                status_text.info("🎬 영상을 조립하는 중입니다... (거의 다 왔습니다!)")

                # 2. FFmpeg용 시간표(텍스트 파일) 만들기
                concat_file_path = os.path.join("temp_workspace", "concat_list.txt")
                with open(concat_file_path, "w", encoding="utf-8") as f:
                    for i, duration in enumerate(scene_durations):
                        f.write(f"file '{os.path.abspath(resized_paths[i])}'\n")
                        f.write(f"duration {duration}\n")
                    if resized_paths:
                        f.write(f"file '{os.path.abspath(resized_paths[-1])}'\n")

                output_path = os.path.join("temp_workspace", "완성본_영상.mp4")
                
                # 3. 엄청 가벼운 원시 엔진(FFmpeg)으로 조립 렌더링
                with st.spinner(f"⏳ {len(image_paths)}장의 이미지를 합치고 있습니다. (메모리 초절전 엔진 가동 중!)"):
                    ffmpeg_exe = get_ffmpeg_exe()
                    cmd = [
                        ffmpeg_exe, "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", concat_file_path,
                        "-i", audio_path,
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-c:a", "aac",
                        "-shortest",
                        output_path
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        raise RuntimeError(f"엔진 렌더링 오류: {result.stderr}")
                
                status_text.empty()
                st.success("🎉 렌더링 완료! 대본 싱크가 완벽하게 맞는 영상이 완성되었습니다!")
                st.balloons()
                
                with open(output_path, "rb") as file:
                    st.download_button(label="📥 완성된 영상 다운로드 하기", data=file, file_name="Ai돈나_초고속_영상.mp4", mime="video/mp4", type="primary", use_container_width=True)
                    
        except Exception as e:
            st.error("🚨 앗! 영상 변환 중 문제가 발생했습니다.")
            st.warning("""
            **💡 [자주 발생하는 오류 원인]**
            1. **대본 오류:** 대본(.txt) 파일에 '엔터 2번(빈 줄)'이 제대로 안 들어갔거나, 불필요한 기호가 섞여 있습니다.
            2. **자막 오류:** 자막(.srt) 파일의 내용이 비정상적입니다.
            
            새로고침(F5) 후 파일을 확인하고 다시 시도해 주세요!
            """)
            with st.expander("🛠️ 상세 에러 로그 (관리자 확인용)"):
                st.write(traceback.format_exc())
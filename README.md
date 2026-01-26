# Process GPT React Voice Agent

## 설치 및 실행 

### 로컬 개발 환경

1. 의존성 설치:
```bash
uv pip install -r requirements.txt
```

2. 환경 변수 설정:
```bash
cp .env.example .env
# .env 파일에 다음 변수들을 설정하세요:
# OPENAI_API_KEY=your_openai_api_key
# SUPABASE_URL=your_supabase_url
# SUPABASE_KEY=your_supabase_key
```

3. 서버 실행:
```bash
uv run server/app.py
```

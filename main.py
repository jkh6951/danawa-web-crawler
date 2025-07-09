from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
import json
import uuid
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import csv
import time
import random
import re
from urllib.parse import quote
from typing import List

# FastAPI 앱 생성
app = FastAPI(title="다나와 프로 크롤러")

# 크롤링 작업 상태 저장
crawling_jobs = {}
active_connections: List[WebSocket] = []

class DanawaWebCrawler:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.session = requests.Session()
        # 더 정교한 브라우저 헤더로 봇 차단 우회
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1'
        })
        self.status = "준비중"
        self.progress = 0
        self.total_items = 0
        self.current_item = 0
        self.results = []
        
    async def notify_progress(self, message: str):
        """WebSocket으로 진행상황 전송"""
        for connection in active_connections:
            try:
                await connection.send_text(json.dumps({
                    "job_id": self.job_id,
                    "status": self.status,
                    "progress": self.progress,
                    "current_item": self.current_item,
                    "total_items": self.total_items,
                    "message": message
                }))
            except:
                pass
    
    async def crawl_danawa(self, keyword: str, max_pages: int = 3):
        """다나와 크롤링 메인 함수"""
        try:
            self.status = "시작"
            await self.notify_progress(f"'{keyword}' 검색을 시작합니다...")
            
            # 기본 정보 수집
            basic_products = await self.collect_basic_info(keyword, max_pages)
            
            if not basic_products:
                self.status = "실패"
                await self.notify_progress("상품을 찾을 수 없습니다.")
                return []
            
            self.total_items = len(basic_products)
            self.status = "완료"
            self.results = basic_products
            await self.notify_progress(f"총 {len(basic_products)}개 상품 수집 완료!")
            
            return basic_products
            
        except Exception as e:
            self.status = "오류"
            await self.notify_progress(f"오류 발생: {str(e)}")
            return []
    
    async def collect_basic_info(self, keyword: str, max_pages: int):
        """기본 상품 정보 수집 - 개선된 버전"""
        products = []
        
        for page in range(1, max_pages + 1):
            await self.notify_progress(f"🌐 {page}페이지 접속 준비 중...")
            
            # URL 인코딩 개선
            encoded_keyword = quote(keyword.encode('utf-8'))
            url = f"https://search.danawa.com/dsearch.php?query={encoded_keyword}&sort=opinionDESC&list=list&boost=true&limit=40&mode=simple&page={page}"
            
            try:
                await self.notify_progress(f"📡 {page}페이지 요청 중...")
                
                # 더 긴 타임아웃과 재시도
                response = self.session.get(url, timeout=20)
                
                await self.notify_progress(f"📨 응답 수신: {response.status_code}")
                
                if response.status_code != 200:
                    await self.notify_progress(f"❌ HTTP 오류: {response.status_code}")
                    continue
                
                response.raise_for_status()
                
                await self.notify_progress(f"🔍 HTML 내용 분석 중...")
                
                # HTML 내용 길이 확인
                html_length = len(response.text)
                await self.notify_progress(f"📄 HTML 크기: {html_length:,} 바이트")
                
                if html_length < 1000:
                    await self.notify_progress(f"⚠️ HTML이 너무 작음 - 차단되었을 가능성")
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                await self.notify_progress(f"🎯 상품 정보 추출 중...")
                page_products = self.extract_products_from_page(soup)
                
                if not page_products:
                    await self.notify_progress(f"❌ {page}페이지에서 상품을 찾을 수 없습니다.")
                    # HTML 구조 확인을 위한 디버깅
                    title = soup.find('title')
                    if title:
                        await self.notify_progress(f"📰 페이지 제목: {title.get_text()[:50]}")
                    break
                
                products.extend(page_products)
                await self.notify_progress(f"✅ {page}페이지: {len(page_products)}개 상품 발견")
                
                # 페이지 간 더 긴 대기 (봇 차단 방지)
                if page < max_pages:
                    await self.notify_progress(f"⏱️ 다음 페이지 대기 중...")
                    time.sleep(random.uniform(3, 6))
                
            except Exception as e:
                await self.notify_progress(f"💥 {page}페이지 오류: {str(e)}")
                break
        
        return products
    
    def extract_products_from_page(self, soup):
        """페이지에서 상품 정보 추출 - 디버깅 강화"""
        products = []
        
        # 다양한 선택자로 상품 리스트 찾기
        selectors = [
            'ul.product_list li',
            '.main_prodlist li', 
            '.prod_list li',
            'li.prod_item',
            '.item_wrap',
            '.product_item'
        ]
        
        items = []
        used_selector = ""
        
        for selector in selectors:
            items = soup.select(selector)
            if items:
                used_selector = selector
                break
        
        print(f"디버깅: 사용된 선택자 '{used_selector}', 찾은 항목 수: {len(items)}")
        
        if not items:
            # 페이지 구조 분석
            all_li = soup.select('li')
            all_div = soup.select('div')
            print(f"디버깅: 전체 li 태그 수: {len(all_li)}, div 태그 수: {len(all_div)}")
            return products
        
        for i, item in enumerate(items[:50]):  # 최대 50개만 처리
            try:
                product = self.extract_single_product(item)
                if product:
                    products.append(product)
                    if len(products) >= 40:  # 페이지당 40개 제한
                        break
            except Exception as e:
                print(f"디버깅: {i}번째 아이템 처리 오류: {e}")
                continue
                
        return products
    
    def extract_single_product(self, item):
        """개별 상품 정보 추출"""
        name = self.get_product_name(item)
        if not name or len(name.strip()) < 3:
            return None
        
        price = self.get_price(item)
        product_url = self.get_product_url(item)
        
        if name and price > 0:
            return {
                'name': name.strip(),
                'price': price,
                'product_url': product_url,
                'coupang_search_url': f"https://www.coupang.com/np/search?q={quote(name.strip())}"
            }
        
        return None
    
    def get_product_name(self, item):
        """상품명 추출 - 강화된 버전"""
        selectors = [
            'p.prod_name a',
            'dt.prod_name a', 
            'div.prod_name a',
            'a.prod_name',
            '.prod_name a',
            'a[title]',
            '.item_name a',
            '.product_name a',
            'h3 a',
            'h4 a'
        ]
        
        for selector in selectors:
            elem = item.select_one(selector)
            if elem:
                # 텍스트 우선
                text = elem.get_text(strip=True)
                if text and len(text) > 3:
                    return self.clean_name(text)
                
                # title 속성 확인
                title = elem.get('title', '').strip()
                if title and len(title) > 3:
                    return self.clean_name(title)
        
        # 추가 시도: 모든 a 태그 확인
        all_links = item.select('a')
        for link in all_links:
            text = link.get_text(strip=True)
            if text and len(text) > 10 and '원' not in text:  # 가격이 아닌 것들만
                return self.clean_name(text)
        
        return None
    
    def get_price(self, item):
        """가격 추출 - 강화된 버전"""
        selectors = [
            'strong.num',
            'em.num_c', 
            '.price strong',
            'span.price',
            '.price_sect strong',
            '.item_price strong',
            '.product_price strong',
            '.price .num',
            'em[class*="price"]',
            'span[class*="price"]'
        ]
        
        for selector in selectors:
            elem = item.select_one(selector)
            if elem:
                price_text = re.sub(r'[^\d]', '', elem.get_text())
                if price_text and len(price_text) >= 3:  # 최소 3자리 이상
                    try:
                        price = int(price_text)
                        if 1000 <= price <= 10000000:  # 1천원~1천만원 범위
                            return price
                    except:
                        continue
        
        # 추가 시도: 원이 포함된 텍스트 찾기
        text_content = item.get_text()
        price_matches = re.findall(r'([\d,]+)\s*원', text_content)
        for match in price_matches:
            try:
                price = int(match.replace(',', ''))
                if 1000 <= price <= 10000000:
                    return price
            except:
                continue
        
        return 0
    
    def get_product_url(self, item):
        """상품 URL 추출"""
        selectors = [
            'p.prod_name a',
            'dt.prod_name a',
            'a.prod_name'
        ]
        
        for selector in selectors:
            elem = item.select_one(selector)
            if elem:
                href = elem.get('href', '')
                if href:
                    if href.startswith('//'):
                        return 'https:' + href
                    elif href.startswith('/'):
                        return 'https://www.danawa.com' + href
                    return href
        
        return ''
    
    def clean_name(self, name):
        """상품명 정리"""
        import html
        name = html.unescape(name)
        
        patterns = [r'\[.*?무료배송.*?\]', r'\[.*?특가.*?\]', r'\[.*?이벤트.*?\]', r'★+', r'☆+']
        
        for pattern in patterns:
            name = re.sub(pattern, '', name, flags=re.IGNORECASE)
        
        return re.sub(r'\s+', ' ', name).strip()

# HTML 웹 인터페이스 (모바일 최적화)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🛒 다나와 프로 크롤러</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 10px;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }

        .header {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            padding: 20px;
            text-align: center;
            color: white;
        }

        .header h1 {
            font-size: 2em;
            margin-bottom: 10px;
            font-weight: 700;
        }

        .header p {
            font-size: 1em;
            opacity: 0.9;
        }

        .main-content {
            padding: 20px;
        }

        .search-form {
            background: #f8f9ff;
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 20px;
            border: 2px solid #e3e8ff;
        }

        .form-group {
            margin-bottom: 15px;
        }

        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #374151;
            font-size: 1em;
        }

        .form-group input, .form-group select {
            width: 100%;
            padding: 12px;
            border: 2px solid #d1d5db;
            border-radius: 10px;
            font-size: 1em;
            transition: all 0.3s ease;
        }

        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: #4facfe;
            box-shadow: 0 0 0 3px rgba(79, 172, 254, 0.1);
        }

        .form-row {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 15px;
            align-items: end;
        }

        .btn-primary {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 10px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            width: 100%;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(79, 172, 254, 0.3);
        }

        .btn-primary:disabled {
            background: #9ca3af;
            cursor: not-allowed;
            transform: none;
        }

        .status-panel {
            background: #f0f9ff;
            border: 2px solid #0ea5e9;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            display: none;
        }

        .status-panel.show {
            display: block;
        }

        .status-header {
            display: flex;
            align-items: center;
            margin-bottom: 15px;
        }

        .status-icon {
            font-size: 1.2em;
            margin-right: 10px;
        }

        .progress-bar {
            width: 100%;
            height: 20px;
            background: #e5e7eb;
            border-radius: 10px;
            overflow: hidden;
            margin: 15px 0;
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%);
            width: 0%;
            transition: width 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 0.9em;
        }

        .results-section {
            background: #f9fafb;
            border-radius: 15px;
            padding: 20px;
            display: none;
        }

        .results-section.show {
            display: block;
        }

        .results-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            flex-wrap: wrap;
            gap: 10px;
        }

        .results-title {
            font-size: 1.3em;
            font-weight: 600;
            color: #1f2937;
        }

        .download-buttons {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }

        .btn-download {
            background: #10b981;
            color: white;
            border: none;
            padding: 8px 15px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 0.9em;
        }

        .btn-download:hover {
            background: #059669;
            transform: translateY(-1px);
        }

        .results-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }

        .results-table th {
            background: #374151;
            color: white;
            padding: 12px 8px;
            text-align: left;
            font-weight: 600;
            font-size: 0.9em;
        }

        .results-table td {
            padding: 12px 8px;
            border-bottom: 1px solid #e5e7eb;
            font-size: 0.9em;
        }

        .results-table tr:hover {
            background: #f9fafb;
        }

        .price {
            font-weight: 600;
            color: #dc2626;
        }

        .rank {
            background: #4facfe;
            color: white;
            padding: 4px 8px;
            border-radius: 15px;
            font-weight: 600;
            text-align: center;
            font-size: 0.8em;
        }

        .product-name {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 250px;
            line-height: 1.3;
        }

        .link-btn {
            background: #6366f1;
            color: white;
            text-decoration: none;
            padding: 4px 10px;
            border-radius: 5px;
            font-size: 0.8em;
            font-weight: 500;
            transition: all 0.3s ease;
            display: inline-block;
        }

        .link-btn:hover {
            background: #4f46e5;
        }

        .coupang-btn {
            background: #ff6b6b;
        }

        .coupang-btn:hover {
            background: #ee5a5a;
        }

        .loading {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid #f3f3f3;
            border-top: 2px solid #4facfe;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .alert {
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 15px;
            font-size: 0.9em;
        }

        .alert-success {
            background: #d1fae5;
            border: 1px solid #10b981;
            color: #047857;
        }

        .alert-error {
            background: #fee2e2;
            border: 1px solid #dc2626;
            color: #991b1b;
        }

        /* 모바일 최적화 */
        @media (max-width: 768px) {
            body {
                padding: 5px;
            }
            
            .container {
                border-radius: 15px;
            }
            
            .header {
                padding: 15px;
            }
            
            .header h1 {
                font-size: 1.5em;
            }
            
            .main-content {
                padding: 15px;
            }
            
            .search-form {
                padding: 15px;
            }
            
            .form-row {
                grid-template-columns: 1fr;
                gap: 10px;
            }
            
            .results-header {
                flex-direction: column;
                align-items: stretch;
            }
            
            .download-buttons {
                justify-content: center;
            }
            
            /* 모바일에서 상품명 여러 줄 표시 */
            .product-name {
                white-space: normal;
                text-overflow: unset;
                max-width: none;
                line-height: 1.4;
                word-break: break-word;
                padding: 8px 4px;
            }
            
            .results-table {
                font-size: 0.8em;
            }
            
            .results-table th,
            .results-table td {
                padding: 8px 4px;
            }
            
            .results-table th {
                font-size: 0.8em;
            }
            
            .rank {
                padding: 3px 6px;
                font-size: 0.7em;
            }
            
            .link-btn {
                padding: 3px 8px;
                font-size: 0.7em;
                margin: 1px;
            }
            
            /* 모바일에서 테이블 열 너비 조정 */
            .results-table th:nth-child(1),
            .results-table td:nth-child(1) {
                width: 60px;
                text-align: center;
            }
            
            .results-table th:nth-child(2),
            .results-table td:nth-child(2) {
                width: auto;
                min-width: 150px;
            }
            
            .results-table th:nth-child(3),
            .results-table td:nth-child(3) {
                width: 80px;
            }
            
            .results-table th:nth-child(4),
            .results-table td:nth-child(4),
            .results-table th:nth-child(5),
            .results-table td:nth-child(5) {
                width: 60px;
                text-align: center;
            }
        }

        /* 초소형 모바일 (320px 이하) */
        @media (max-width: 380px) {
            .header h1 {
                font-size: 1.3em;
            }
            
            .results-table {
                font-size: 0.75em;
            }
            
            .results-table th,
            .results-table td {
                padding: 6px 2px;
            }
            
            .product-name {
                font-size: 0.85em;
            }
            
            .link-btn {
                font-size: 0.65em;
                padding: 2px 6px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🛒 다나와 프로 크롤러</h1>
            <p>실시간 상품 정보 수집 시스템</p>
        </div>

        <div class="main-content">
            <!-- 검색 폼 -->
            <div class="search-form">
                <form id="crawlForm">
                    <div class="form-row">
                        <div class="form-group">
                            <label for="keyword">🔍 검색할 상품명</label>
                            <input type="text" id="keyword" name="keyword" placeholder="예: 의자, 책상, 모니터..." required>
                        </div>
                        <div class="form-group">
                            <label for="pages">📖 페이지 수</label>
                            <select id="pages" name="pages">
                                <option value="1">1페이지</option>
                                <option value="2">2페이지</option>
                                <option value="3" selected>3페이지</option>
                                <option value="4">4페이지</option>
                                <option value="5">5페이지</option>
                            </select>
                        </div>
                    </div>
                    <div class="form-group" style="margin-top: 15px;">
                        <button type="submit" class="btn-primary" id="startBtn">
                            🚀 크롤링 시작
                        </button>
                    </div>
                </form>
            </div>

            <!-- 상태 패널 -->
            <div class="status-panel" id="statusPanel">
                <div class="status-header">
                    <span class="status-icon">📊</span>
                    <h3>크롤링 진행상황</h3>
                </div>
                <div id="statusMessage">준비 중...</div>
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill">0%</div>
                </div>
                <div id="detailStatus"></div>
            </div>

            <!-- 결과 섹션 -->
            <div class="results-section" id="resultsSection">
                <div class="results-header">
                    <h3 class="results-title">📋 크롤링 결과</h3>
                    <div class="download-buttons">
                        <button class="btn-download" onclick="downloadResults('csv')">📊 CSV</button>
                        <button class="btn-download" onclick="downloadResults('json')">📄 JSON</button>
                    </div>
                </div>
                <div id="resultsContainer"></div>
            </div>
        </div>
    </div>

    <script>
        let currentJobId = null;
        let ws = null;

        // WebSocket 연결
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
            
            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                updateProgress(data);
            };
            
            ws.onclose = function() {
                setTimeout(connectWebSocket, 3000); // 재연결 시도
            };
        }

        // 폼 제출 처리
        document.getElementById('crawlForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData();
            formData.append('keyword', document.getElementById('keyword').value);
            formData.append('pages', document.getElementById('pages').value);
            
            // UI 상태 변경
            document.getElementById('startBtn').disabled = true;
            document.getElementById('startBtn').innerHTML = '<span class="loading"></span> 크롤링 중...';
            document.getElementById('statusPanel').classList.add('show');
            document.getElementById('resultsSection').classList.remove('show');
            
            try {
                const response = await fetch('/api/crawl/start', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                currentJobId = result.job_id;
                
                document.getElementById('statusMessage').textContent = result.message;
                
            } catch (error) {
                showAlert('크롤링 시작 중 오류가 발생했습니다: ' + error.message, 'error');
                resetUI();
            }
        });

        // 진행상황 업데이트
        function updateProgress(data) {
            if (data.job_id !== currentJobId) return;
            
            const progressFill = document.getElementById('progressFill');
            const statusMessage = document.getElementById('statusMessage');
            const detailStatus = document.getElementById('detailStatus');
            
            progressFill.style.width = data.progress + '%';
            progressFill.textContent = data.progress + '%';
            statusMessage.textContent = data.message;
            
            if (data.total_items > 0) {
                detailStatus.textContent = `${data.current_item}/${data.total_items} 상품 처리 완료`;
            }
            
            // 완료 시 결과 로드
            if (data.status === '완료') {
                loadResults();
                resetUI();
                showAlert('크롤링이 성공적으로 완료되었습니다!', 'success');
            } else if (data.status === '실패' || data.status === '오류') {
                resetUI();
                showAlert('크롤링 중 오류가 발생했습니다.', 'error');
            }
        }

        // 결과 로드
        async function loadResults() {
            if (!currentJobId) return;
            
            try {
                const response = await fetch(`/api/crawl/results/${currentJobId}`);
                const data = await response.json();
                
                if (data.results && data.results.length > 0) {
                    displayResults(data.results);
                    document.getElementById('resultsSection').classList.add('show');
                }
            } catch (error) {
                showAlert('결과를 불러오는 중 오류가 발생했습니다.', 'error');
            }
        }

        // 결과 표시
        function displayResults(results) {
            const container = document.getElementById('resultsContainer');
            
            let html = `
                <table class="results-table">
                    <thead>
                        <tr>
                            <th>순위</th>
                            <th>상품명</th>
                            <th>가격</th>
                            <th>다나와</th>
                            <th>쿠팡</th>
                        </tr>
                    </thead>
                    <tbody>
            `;
            
            results.forEach((product, index) => {
                html += `
                    <tr>
                        <td><span class="rank">${index + 1}</span></td>
                        <td class="product-name" title="${product.name}">${product.name}</td>
                        <td class="price">${product.price.toLocaleString()}원</td>
                        <td>
                            ${product.product_url ? 
                                `<a href="${product.product_url}" target="_blank" class="link-btn">다나와</a>` : 
                                '-'}
                        </td>
                        <td>
                            <a href="${product.coupang_search_url}" target="_blank" class="link-btn coupang-btn">쿠팡</a>
                        </td>
                    </tr>
                `;
            });
            
            html += '</tbody></table>';
            container.innerHTML = html;
        }

        // 결과 다운로드
        async function downloadResults(format) {
            if (!currentJobId) return;
            
            const url = `/api/crawl/download/${currentJobId}?format=${format}`;
            window.open(url, '_blank');
        }

        // UI 리셋
        function resetUI() {
            document.getElementById('startBtn').disabled = false;
            document.getElementById('startBtn').innerHTML = '🚀 크롤링 시작';
        }

        // 알림 표시
        function showAlert(message, type) {
            const alertDiv = document.createElement('div');
            alertDiv.className = `alert alert-${type}`;
            alertDiv.textContent = message;
            
            const mainContent = document.querySelector('.main-content');
            mainContent.insertBefore(alertDiv, mainContent.firstChild);
            
            setTimeout(() => {
                alertDiv.remove();
            }, 5000);
        }

        // 페이지 로드 시 WebSocket 연결
        window.addEventListener('load', function() {
            connectWebSocket();
        });
    </script>
</body>
</html>
"""

# API 엔드포인트들
@app.get("/", response_class=HTMLResponse)
async def read_root():
    """메인 페이지 - 완전한 웹 인터페이스"""
    return HTMLResponse(content=HTML_TEMPLATE)

@app.get("/test")
async def test():
    return {"message": "서버가 살아있어요!", "status": "OK"}

@app.post("/api/crawl/start")
async def start_crawling(background_tasks: BackgroundTasks, keyword: str = Form(...), pages: int = Form(...)):
    """크롤링 시작"""
    job_id = str(uuid.uuid4())
    
    crawler = DanawaWebCrawler(job_id)
    crawling_jobs[job_id] = crawler
    
    background_tasks.add_task(crawler.crawl_danawa, keyword, pages)
    
    return {"job_id": job_id, "status": "시작됨", "message": f"'{keyword}' 크롤링이 시작되었습니다."}

@app.get("/api/crawl/status/{job_id}")
async def get_crawling_status(job_id: str):
    """크롤링 상태 조회"""
    if job_id not in crawling_jobs:
        return {"error": "작업을 찾을 수 없습니다."}
    
    crawler = crawling_jobs[job_id]
    return {
        "job_id": job_id,
        "status": crawler.status,
        "progress": crawler.progress,
        "current_item": crawler.current_item,
        "total_items": crawler.total_items,
        "result_count": len(crawler.results)
    }

@app.get("/api/crawl/results/{job_id}")
async def get_crawling_results(job_id: str):
    """크롤링 결과 조회"""
    if job_id not in crawling_jobs:
        return {"error": "작업을 찾을 수 없습니다."}
    
    crawler = crawling_jobs[job_id]
    return {
        "job_id": job_id,
        "status": crawler.status,
        "results": crawler.results,
        "total_count": len(crawler.results)
    }

@app.get("/api/crawl/download/{job_id}")
async def download_results(job_id: str, format: str = "csv"):
    """결과 다운로드"""
    if job_id not in crawling_jobs:
        return {"error": "작업을 찾을 수 없습니다."}
    
    crawler = crawling_jobs[job_id]
    
    if format == "csv":
        filename = f"danawa_results_{job_id[:8]}.csv"
        
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            if crawler.results:
                fieldnames = ['name', 'price', 'product_url', 'coupang_search_url']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(crawler.results)
        
        return FileResponse(filename, filename=filename)
    
    elif format == "json":
        filename = f"danawa_results_{job_id[:8]}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(crawler.results, f, ensure_ascii=False, indent=2)
        
        return FileResponse(filename, filename=filename)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 연결"""
    await websocket.accept()
    active_connections.append(websocket)
    
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)

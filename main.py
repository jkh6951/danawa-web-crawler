from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
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

# 템플릿 설정
templates = Jinja2Templates(directory="templates")

# 크롤링 작업 상태 저장
crawling_jobs = {}
active_connections: List[WebSocket] = []

class DanawaWebCrawler:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
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
        """기본 상품 정보 수집"""
        products = []
        
        for page in range(1, max_pages + 1):
            await self.notify_progress(f"{page}페이지 수집 중...")
            
            url = f"https://search.danawa.com/dsearch.php?query={keyword}&sort=opinionDESC&list=list&boost=true&limit=40&mode=simple&page={page}"
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                page_products = self.extract_products_from_page(soup)
                
                if not page_products:
                    await self.notify_progress(f"{page}페이지에서 상품을 찾을 수 없습니다.")
                    break
                
                products.extend(page_products)
                await self.notify_progress(f"{page}페이지: {len(page_products)}개 상품 발견")
                
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                await self.notify_progress(f"{page}페이지 오류: {str(e)}")
                break
        
        return products
    
    def extract_products_from_page(self, soup):
        """페이지에서 상품 정보 추출"""
        products = []
        selectors = ['ul.product_list li', '.main_prodlist li', '.prod_list li', 'li.prod_item']
        
        items = []
        for selector in selectors:
            items = soup.select(selector)
            if items:
                break
        
        for item in items:
            try:
                product = self.extract_single_product(item)
                if product:
                    products.append(product)
            except:
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
        """상품명 추출"""
        selectors = ['p.prod_name a', 'dt.prod_name a', 'div.prod_name a', 'a.prod_name', '.prod_name a']
        
        for selector in selectors:
            elem = item.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                if text and len(text) > 3:
                    return self.clean_name(text)
                
                title = elem.get('title', '').strip()
                if title and len(title) > 3:
                    return self.clean_name(title)
        
        return None
    
    def get_price(self, item):
        """가격 추출"""
        selectors = ['strong.num', 'em.num_c', '.price strong', 'span.price', '.price_sect strong']
        
        for selector in selectors:
            elem = item.select_one(selector)
            if elem:
                price_text = re.sub(r'[^\d]', '', elem.get_text())
                if price_text:
                    try:
                        return int(price_text)
                    except:
                        continue
        
        return 0
    
    def get_product_url(self, item):
        """상품 URL 추출"""
        selectors = ['p.prod_name a', 'dt.prod_name a', 'a.prod_name']
        
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

# API 엔드포인트들
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """메인 페이지"""
    return templates.TemplateResponse("index.html", {"request": request})

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

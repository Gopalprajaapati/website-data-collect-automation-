from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
import pandas as pd
from googlesearch import search
from urllib.parse import urlparse
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import threading
# Add these new imports at the top
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
import time

# Initialize Flask and Database
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///resultss.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.secret_key = 'your-secret-key-here'

db = SQLAlchemy(app)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# Define database models
class Keyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, in_progress, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)


class SearchResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    keyword_id = db.Column(db.Integer, db.ForeignKey('keyword.id'), nullable=False)
    title = db.Column(db.String(200), nullable=True)
    link = db.Column(db.String(500), nullable=True)
    website = db.Column(db.String(500), nullable=True)
    stars = db.Column(db.Float, nullable=True)
    reviews = db.Column(db.Integer, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    facebook = db.Column(db.String(500), nullable=True)
    instagram = db.Column(db.String(500), nullable=True)
    linkedin = db.Column(db.String(500), nullable=True)
    twitter = db.Column(db.String(500), nullable=True)
    scraped_at = db.Column(db.DateTime, default=datetime.utcnow)

    keyword = db.relationship('Keyword', backref='results')


# Initialize the database
with app.app_context():
    db.create_all()


# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ['xlsx', 'xls', 'csv']


def process_excel(filepath):
    try:
        # Read file based on extension
        if filepath.endswith('.csv'):
            df = pd.read_csv(filepath)
        else:  # .xlsx or .xls
            df = pd.read_excel(filepath)

        # Get first column and clean data
        keywords = df.iloc[:, 0].astype(str).str.strip().dropna().unique().tolist()

        # Remove empty strings after stripping
        keywords = [kw for kw in keywords if kw]

        return keywords
    except Exception as e:
        print(f"Error processing file: {e}")
        return []


# Add this function to analyze website quality
def analyze_website(url):
    if not url or not url.startswith(('http://', 'https://')):
        return {
            'mobile_friendly': False,
            'load_time': None,
            'professional_look': False,
            'issues': ['Invalid URL'],
            'score': 0
        }

    try:
        start_time = time.time()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        load_time = time.time() - start_time

        soup = BeautifulSoup(response.text, 'html.parser')

        # Check for mobile-friendliness
        viewport = soup.find('meta', attrs={'name': 'viewport'})
        mobile_friendly = bool(viewport)

        # Check for professional look
        professional_look = True
        issues = []

        # Check for common CMS/template indicators
        generator = soup.find('meta', attrs={'name': 'generator'})
        if generator:
            issues.append(f"Uses {generator.get('content', 'unknown CMS')}")

        # Check for common problematic keywords in HTML
        html_text = str(soup).lower()
        problematic_keywords = ['wix', 'weebly', 'template', 'outdated', 'under construction']
        found_keywords = [kw for kw in problematic_keywords if kw in html_text]
        if found_keywords:
            issues.extend(found_keywords)
            professional_look = False

        # Check for very basic HTML (might indicate poor quality)
        if len(soup.find_all()) < 50:
            issues.append("Very basic HTML structure")
            professional_look = False

        # Calculate score (0-100)
        score = 0
        if mobile_friendly:
            score += 40
        if load_time < 3:
            score += 30
        if professional_look:
            score += 30

        return {
            'mobile_friendly': mobile_friendly,
            'load_time': round(load_time, 2),
            'professional_look': professional_look,
            'issues': issues if issues else ['No major issues found'],
            'score': score
        }

    except Exception as e:
        return {
            'mobile_friendly': False,
            'load_time': None,
            'professional_look': False,
            'issues': [f"Error analyzing: {str(e)}"],
            'score': 0
        }


# Add this new route for website quality analysis
@app.route('/analyze_websites', methods=['GET', 'POST'])
def analyze_websites():
    # Get filter parameters
    filter_type = request.args.get('filter', 'all')

    # Get all results with websites
    query = SearchResult.query.filter(SearchResult.website.isnot(None))

    # Apply filters
    if filter_type == 'no_website':
        query = SearchResult.query.filter(SearchResult.website.is_(None))
    elif filter_type == 'bad_website':
        # This will be handled after analysis
        pass

    results = query.all()

    # Analyze websites
    analyzed_results = []
    for result in results:
        analysis = {}
        if result.website:
            analysis = analyze_website(result.website)
        else:
            analysis = {
                'mobile_friendly': False,
                'load_time': None,
                'professional_look': False,
                'issues': ['No website'],
                'score': 0
            }

        analyzed_results.append({
            'id': result.id,
            'title': result.title,
            'website': result.website,
            'analysis': analysis
        })

    # Apply bad website filter if selected
    if filter_type == 'bad_website':
        analyzed_results = [r for r in analyzed_results if r['analysis']['score'] < 50]

    # Handle Excel export
    if 'export' in request.args:
        df = pd.DataFrame([{
            'ID': r['id'],
            'Title': r['title'],
            'Website': r['website'],
            'Mobile Friendly': 'Yes' if r['analysis']['mobile_friendly'] else 'No',
            'Load Time (s)': r['analysis']['load_time'],
            'Professional Look': 'Yes' if r['analysis']['professional_look'] else 'No',
            'Issues': ', '.join(r['analysis']['issues']),
            'Score': r['analysis']['score']
        } for r in analyzed_results])

        filename = f"website_analysis_{filter_type}.xlsx"
        df.to_excel(filename, index=False)
        return send_file(filename, as_attachment=True)

    return render_template('analyze_websites.html',
                           results=analyzed_results,
                           filter_type=filter_type)


# Add to your existing imports if not already present
from io import BytesIO


def search_social_media(business_name):
    try:
        search_results = search(business_name, num_results=10)
        social_media_links = {
            "Business Name": business_name,
            "Facebook": None,
            "Instagram": None,
            "LinkedIn": None,
            "Twitter": None
        }

        social_media_domains = {
            "facebook.com": "Facebook",
            "instagram.com": "Instagram",
            "linkedin.com": "LinkedIn",
            "twitter.com": "Twitter"
        }

        for url in search_results:
            parsed_url = urlparse(url)
            domain_name = parsed_url.netloc
            for domain, platform in social_media_domains.items():
                if domain in domain_name:
                    social_media_links[platform] = url
        return social_media_links
    except Exception as e:
        print(f"Error searching social media for {business_name}: {e}")
        return {
            "Business Name": business_name,
            "Facebook": None,
            "Instagram": None,
            "LinkedIn": None,
            "Twitter": None
        }


def run_scraper(keyword_id):
    with app.app_context():
        keyword = Keyword.query.get(keyword_id)
        if not keyword:
            return False

        # Update status to in_progress
        keyword.status = 'in_progress'
        db.session.commit()

        driver = None
        try:
            # Configure Chrome options
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument('--headless')  # Run in background
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')

            # Initialize WebDriver with options
            driver = webdriver.Chrome(options=chrome_options)
            driver.set_page_load_timeout(60)

            driver.get(f'https://www.google.com/maps/search/{keyword.keyword}/')

            # Handle possible pop-ups
            try:
                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "form:nth-child(2)"))).click()
            except Exception:
                pass

            # Scroll to load all results
            scrollable_div = driver.find_element(By.CSS_SELECTOR, 'div[role="feed"]')
            last_height = driver.execute_script("return arguments[0].scrollHeight", scrollable_div)
            scroll_attempts = 0
            max_scroll_attempts = 10  # Prevent infinite scrolling

            while scroll_attempts < max_scroll_attempts:
                driver.execute_script("arguments[0].scrollBy(0, arguments[0].scrollHeight)", scrollable_div)
                time.sleep(2)  # Wait for new results to load
                new_height = driver.execute_script("return arguments[0].scrollHeight", scrollable_div)

                if new_height == last_height:
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0
                    last_height = new_height

            # Scrape results
            items = driver.find_elements(By.CSS_SELECTOR, 'div[role="feed"] > div > div[jsaction]')
            results = []

            for item in items:
                data = {'keyword_id': keyword_id}

                try:
                    data['title'] = item.find_element(By.CSS_SELECTOR, ".fontHeadlineSmall").text
                except Exception:
                    continue  # Skip if no title

                try:
                    data['link'] = item.find_element(By.CSS_SELECTOR, "a").get_attribute('href')
                except Exception:
                    pass

                try:
                    data['website'] = item.find_element(By.CSS_SELECTOR,
                                                        'div[role="feed"] > div > div[jsaction] div > a').get_attribute(
                        'href')
                except Exception:
                    pass

                try:
                    rating_text = item.find_element(By.CSS_SELECTOR,
                                                    '.fontBodyMedium > span[role="img"]').get_attribute('aria-label')
                    rating_numbers = [float(piece.replace(",", ".")) for piece in rating_text.split(" ") if
                                      piece.replace(",", ".").replace(".", "", 1).isdigit()]
                    if rating_numbers:
                        data['stars'] = rating_numbers[0]
                        data['reviews'] = int(rating_numbers[1]) if len(rating_numbers) > 1 else 0
                except Exception:
                    pass

                try:
                    text_content = item.text
                    phone_pattern = r'((\+?\d{1,2}[ -]?)?(\(?\d{3}\)?[ -]?\d{3,4}[ -]?\d{4}|\(?\d{2,3}\)?[ -]?\d{2,3}[ -]?\d{2,3}[ -]?\d{2,3}))'
                    matches = re.findall(phone_pattern, text_content)
                    phone_numbers = [match[0] for match in matches]
                    unique_phone_numbers = list(set(phone_numbers))
                    data['phone'] = unique_phone_numbers[0] if unique_phone_numbers else None
                except Exception:
                    pass

                # Get social media links
                if data.get('title'):
                    social_links = search_social_media(data['title'])
                    data['facebook'] = social_links.get("Facebook")
                    data['instagram'] = social_links.get("Instagram")
                    data['linkedin'] = social_links.get("LinkedIn")
                    data['twitter'] = social_links.get("Twitter")

                    result = SearchResult(**data)
                    db.session.add(result)
                    results.append(data)

            # Update status to completed
            keyword.status = 'completed'
            keyword.completed_at = datetime.utcnow()
            db.session.commit()
            return True

        except Exception as e:
            print(f"Error scraping for keyword {keyword.keyword}: {e}")
            keyword.status = 'error'
            db.session.commit()
            return False
        finally:
            if driver:
                driver.quit()


# Routes
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        keyword = request.form.get('keyword')
        if keyword:
            new_keyword = Keyword(keyword=keyword)
            db.session.add(new_keyword)
            db.session.commit()
            flash('Keyword added successfully!', 'success')
            return redirect(url_for('keywords'))

    keywords = Keyword.query.order_by(Keyword.id.desc()).all()
    return render_template('index.html', keywords=keywords)


@app.route('/keywords', methods=['GET'])
def keywords():
    keywords = Keyword.query.order_by(Keyword.id.desc()).all()
    return render_template('keywords.html', keywords=keywords)


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(request.url)

    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('index'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        try:
            # Process Excel file
            keywords = process_excel(filepath)

            # Remove duplicates while preserving order
            seen = set()
            unique_keywords = []
            for kw in keywords:
                if kw not in seen:
                    seen.add(kw)
                    unique_keywords.append(kw)

            # Count duplicates removed
            duplicates_removed = len(keywords) - len(unique_keywords)

            # Add only new keywords that don't exist in database
            added = 0
            for kw in unique_keywords:
                if not Keyword.query.filter_by(keyword=kw).first():
                    db.session.add(Keyword(keyword=kw))
                    added += 1

            db.session.commit()

            # Prepare feedback message
            message = f'{added} new keywords imported successfully!'
            if duplicates_removed > 0:
                message += f' {duplicates_removed} duplicates removed from file.'
            if len(unique_keywords) - added > 0:
                message += f' {len(unique_keywords) - added} duplicates already in database.'

            flash(message, 'success')
            return redirect(url_for('keywords'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error processing file: {str(e)}', 'error')
            return redirect(url_for('index'))
    else:
        flash('Allowed file types are xlsx, xls, csv', 'error')
        return redirect(url_for('index'))



@app.route('/scrape/<int:keyword_id>', methods=['POST'])
def scrape_keyword(keyword_id):
    # Start scraping in a background thread
    thread = threading.Thread(target=run_scraper, args=(keyword_id,))
    thread.start()

    flash('Scraping started in the background. Please wait...', 'info')
    return redirect(url_for('results', keyword_id=keyword_id))


@app.route('/results/<int:keyword_id>', methods=['GET'])
def results(keyword_id):
    keyword = Keyword.query.get_or_404(keyword_id)
    results = SearchResult.query.filter_by(keyword_id=keyword_id).order_by(SearchResult.scraped_at.desc()).all()
    return render_template('results.html', keyword=keyword, results=results)


@app.route('/delete_keyword/<int:keyword_id>', methods=['POST'])
def delete_keyword(keyword_id):
    keyword = Keyword.query.get_or_404(keyword_id)
    SearchResult.query.filter_by(keyword_id=keyword_id).delete()
    db.session.delete(keyword)
    db.session.commit()
    flash('Keyword and associated results deleted successfully!', 'success')
    return redirect(url_for('keywords'))


# Add these new routes to your existing app.py

@app.route('/searchalldata', methods=['GET', 'POST'])
def search_all_data():
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Items per page

    # Get parameters from either form POST or URL GET
    if request.method == 'POST':
        search_query = request.form.get('search_query', '')
        field = request.form.get('search_field', 'title')
        sort_by = request.form.get('sort_by', 'id')
        sort_order = request.form.get('sort_order', 'asc')
    else:
        search_query = request.args.get('search_query', '')
        field = request.args.get('search_field', 'title')
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'asc')


    # Handle search form submission
    if request.method == 'POST':
        search_query = request.form.get('search_query', '')
        field = request.form.get('search_field', 'title')

        # Build query based on search field
        if field == 'title':
            query = SearchResult.query.filter(SearchResult.title.contains(search_query))
        elif field == 'phone':
            query = SearchResult.query.filter(SearchResult.phone.contains(search_query))
        elif field == 'website':
            query = SearchResult.query.filter(SearchResult.website.contains(search_query))
        elif field == 'keyword':
            query = SearchResult.query.join(Keyword).filter(Keyword.keyword.contains(search_query))
        else:
            query = SearchResult.query

        # Handle bulk actions
        if 'bulk_action' in request.form:
            selected_ids = request.form.getlist('selected_ids')
            if selected_ids:
                if request.form['bulk_action'] == 'delete':
                    SearchResult.query.filter(SearchResult.id.in_(selected_ids)).delete()
                    db.session.commit()
                    flash(f'{len(selected_ids)} records deleted successfully!', 'success')

        # Handle sorting
        sort_by = request.form.get('sort_by', 'id')
        sort_order = request.form.get('sort_order', 'asc')

        if sort_by and sort_order:
            if sort_order == 'asc':
                query = query.order_by(getattr(SearchResult, sort_by).asc())
            else:
                query = query.order_by(getattr(SearchResult, sort_by).desc())
    else:
        search_query = request.args.get('search_query', '')
        field = request.args.get('search_field', 'title')
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'asc')

        if field == 'title':
            query = SearchResult.query.filter(SearchResult.title.contains(search_query))
        elif field == 'phone':
            query = SearchResult.query.filter(SearchResult.phone.contains(search_query))
        elif field == 'website':
            query = SearchResult.query.filter(SearchResult.website.contains(search_query))
        elif field == 'keyword':
            query = SearchResult.query.join(Keyword).filter(Keyword.keyword.contains(search_query))
        else:
            query = SearchResult.query

        if sort_by and sort_order:
            if sort_order == 'asc':
                query = query.order_by(getattr(SearchResult, sort_by).asc())
            else:
                query = query.order_by(getattr(SearchResult, sort_by).desc())

    # Paginate the results
    results = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        'searchalldata.html',
        results=results,
        search_query=search_query,
        search_field=field,
        sort_by=sort_by,
        sort_order=sort_order
    )




# Add this new route to your app.py
@app.route('/quick_search', methods=['GET'])
def quick_search():
    search_query = request.args.get('q', '')  # Get search query from URL parameter
    if not search_query:
        return redirect(url_for('search_all_data'))

    # Redirect to searchalldata page with search parameters
    return redirect(url_for('search_all_data',
                            search_query=search_query,
                            search_field='title',  # Default search field
                            sort_by='id',
                            sort_order='asc'))


@app.route('/update_result/<int:result_id>', methods=['POST'])
def update_result(result_id):
    result = SearchResult.query.get_or_404(result_id)

    result.title = request.form.get('title', result.title)
    result.website = request.form.get('website', result.website)
    result.phone = request.form.get('phone', result.phone)
    result.facebook = request.form.get('facebook', result.facebook)
    result.instagram = request.form.get('instagram', result.instagram)
    result.linkedin = request.form.get('linkedin', result.linkedin)
    result.twitter = request.form.get('twitter', result.twitter)

    db.session.commit()
    flash('Record updated successfully!', 'success')
    return redirect(request.referrer or url_for('search_all_data'))

# Add these new routes to your existing app.py

@app.route('/delete_keywords', methods=['POST'])
def delete_keywords():
    if request.method == 'POST':
        keyword_ids = request.form.getlist('keyword_ids')

        if not keyword_ids:
            flash('No keywords selected for deletion', 'warning')
            return redirect(url_for('keywords'))

        try:
            # Delete selected keywords and their results
            for keyword_id in keyword_ids:
                SearchResult.query.filter_by(keyword_id=keyword_id).delete()
                Keyword.query.filter_by(id=keyword_id).delete()
            db.session.commit()
            flash(f'{len(keyword_ids)} keywords deleted successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error deleting keywords: {str(e)}', 'error')

        return redirect(url_for('keywords'))


@app.route('/run_keywords', methods=['POST'])
def run_keywords():
    if request.method == 'POST':
        keyword_ids = request.form.getlist('keyword_ids')

        if not keyword_ids:
            flash('No keywords selected to run', 'warning')
            return redirect(url_for('keywords'))

        try:
            for keyword_id in keyword_ids:
                # Start scraping in background thread for each keyword
                thread = threading.Thread(target=run_scraper, args=(keyword_id,))
                thread.start()

            flash(f'Started scraping for {len(keyword_ids)} keywords in background', 'info')
        except Exception as e:
            flash(f'Error starting keywords: {str(e)}', 'error')

        return redirect(url_for('keywords'))


@app.route('/delete_result/<int:result_id>', methods=['POST'])
def delete_result(result_id):
    result = SearchResult.query.get_or_404(result_id)
    keyword_id = result.keyword_id
    db.session.delete(result)
    db.session.commit()
    flash('Result deleted successfully!', 'success')
    return redirect(url_for('results', keyword_id=keyword_id))


@app.route('/delete_results', methods=['POST'])
def delete_results():
    if request.method == 'POST':
        result_ids = request.form.getlist('result_ids')
        keyword_id = request.form.get('keyword_id')

        if not result_ids:
            flash('No results selected for deletion', 'warning')
            return redirect(url_for('results', keyword_id=keyword_id))

        try:
            # Delete selected results
            SearchResult.query.filter(SearchResult.id.in_(result_ids)).delete()
            db.session.commit()
            flash(f'{len(result_ids)} results deleted successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error deleting results: {str(e)}', 'error')

        return redirect(url_for('results', keyword_id=keyword_id))


@app.route('/export/<int:keyword_id>', methods=['GET'])
def export_results(keyword_id):
    keyword = Keyword.query.get_or_404(keyword_id)
    results = SearchResult.query.filter_by(keyword_id=keyword_id).all()

    data = []
    for result in results:
        data.append({
            'Title': result.title,
            'Link': result.link,
            'Website': result.website,
            'Stars': result.stars,
            'Reviews': result.reviews,
            'Phone': result.phone,
            'Facebook': result.facebook,
            'Instagram': result.instagram,
            'LinkedIn': result.linkedin,
            'Twitter': result.twitter,
            'Scraped At': result.scraped_at.strftime('%Y-%m-%d %H:%M:%S')
        })

    df = pd.DataFrame(data)
    filename = f"results_{keyword.keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(filename, index=False)

    return send_file(filename, as_attachment=True)


@app.route('/status')
def status():
    keywords = Keyword.query.order_by(Keyword.id.desc()).all()
    return render_template('status.html', keywords=keywords)


if __name__ == "__main__":
    app.run(debug=True)
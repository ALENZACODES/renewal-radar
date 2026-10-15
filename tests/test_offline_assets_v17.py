from fastapi.testclient import TestClient

from renewal.main import app


def test_service_worker_is_served_with_root_scope_and_no_cache():
    with TestClient(app) as http:
        response = http.get('/service-worker.js')
    assert response.status_code == 200
    assert response.headers['service-worker-allowed'] == '/'
    assert response.headers['cache-control'] == 'no-cache'
    assert 'renewal-radar-shell-v20' in response.text


def test_robots_rules_exclude_api_and_private_share_paths():
    with TestClient(app) as http:
        response = http.get('/robots.txt')
    assert response.status_code == 200
    assert 'Disallow: /api/' in response.text
    assert 'Disallow: /shared/' in response.text
    assert 'Allow: /' in response.text


def test_offline_fonts_and_helper_modules_are_served_locally():
    paths = ['/assets/fonts/Lato-Bold.ttf', '/assets/fonts/NotoSans-Variable.ttf',
             '/assets/public-service.css', '/js/helper-classifier.js', '/js/helper-answers.js',
             '/assets/fonts/InterVariable.woff2', '/assets/vendor/echarts-6.1.0.min.js',
             '/js/chart-runtime.js', '/assets/naval-academic.css',
             '/assets/naval-waves.svg', '/assets/renewal-radar-naval-v17.png']
    with TestClient(app) as http:
        for path in paths:
            response = http.get(path)
            assert response.status_code == 200, path
            assert len(response.content) > 100, path


def test_homepage_exposes_helper_and_local_typography_stylesheet():
    with TestClient(app) as http:
        response = http.get('/')
    assert 'helper-launcher' in response.text
    assert '/assets/public-service.css' in response.text
    assert '/assets/vendor/echarts-6.1.0.min.js' in response.text
    assert '/assets/naval-academic.css' in response.text
    assert 'renewal-radar-naval-v17.png' in response.text

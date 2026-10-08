"""Website quản lý thư viện số - Trường Đại học Công nghiệp Việt Trì (Flask)."""
from flask import Flask, render_template
from flask_wtf.csrf import CSRFError

from . import utils
from .config import Config
from .extensions import csrf, db, login_manager, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        user = db.session.get(User, int(user_id))
        # Tài khoản bị khóa/tạm ngưng bị đăng xuất ngay ở request kế tiếp
        return user if user and user.status == 'active' else None

    from .blueprints.admin import bp as admin_bp
    from .blueprints.auth import bp as auth_bp
    from .blueprints.main import bp as main_bp
    from .blueprints.user import bp as user_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')

    app.jinja_env.filters.update(
        money=utils.format_money, date=utils.format_date, datetime=utils.format_datetime,
        filesize=utils.format_filesize, initials=utils.initials,
    )

    @app.context_processor
    def inject_globals():
        from .services import get_setting
        return {'get_setting': get_setting, 'page_url': utils.page_url}

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        return render_template('errors/error.html', code=400,
                               message='Phiên làm việc đã hết hạn, vui lòng tải lại trang và thử lại.'), 400

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/error.html', code=403, message='Bạn không có quyền truy cập trang này.'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/error.html', code=404, message='Không tìm thấy trang yêu cầu.'), 404

    @app.after_request
    def security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        return response

    from . import cli
    cli.register(app)

    return app

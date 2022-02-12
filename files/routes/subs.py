from files.__main__ import app, limiter, mail
from files.helpers.alerts import *
from files.helpers.wrappers import *
from files.classes import *
from .front import frontlist

valid_sub_regex = re.compile("^[a-zA-Z0-9_\-]{3,25}$")

@app.get("/s/<sub>/mods")
@is_not_permabanned
def mods(v, sub):
	sub = g.db.query(Sub).filter_by(name=sub.strip().lower()).one_or_none()
	if not sub: abort(404)

	users = g.db.query(User, Mod).join(Mod, Mod.user_id==User.id).filter_by(sub=sub.name).order_by(Mod.created_utc).all()

	return render_template("sub/mods.html", v=v, sub=sub, users=users)


@app.post("/s/<sub>/add_mod")
@limiter.limit("1/second;5/day")
@is_not_permabanned
def add_mod(v, sub):
	sub = g.db.query(Sub).filter_by(name=sub.strip().lower()).one_or_none()
	if not sub: abort(404)
	sub = sub.name

	if not v.mods(sub): abort(403)

	user = request.values.get('user')

	if not user: abort(400)

	user = get_user(user)

	existing = g.db.query(Mod).filter_by(user_id=user.id, sub=sub).one_or_none()

	if not existing:
		mod = Mod(user_id=user.id, sub=sub, created_utc=int(time.time()))
		g.db.add(mod)

		send_repeatable_notification(user.id, f"You have been added as a mod to /s/{sub}")

		g.db.commit()
	
	return redirect(f'/s/{sub}/mods')


@app.post("/s/<sub>/remove_mod")
@is_not_permabanned
def remove_mod(v, sub):
	sub = g.db.query(Sub).filter_by(name=sub.strip().lower()).one_or_none()
	if not sub: abort(404)
	sub = sub.name

	if not v.mods(sub): abort(403)

	uid = request.values.get('uid')

	if not uid: abort(400)

	try: uid = int(uid)
	except: abort(400)

	mod = g.db.query(Mod).filter_by(user_id=uid, sub=sub).one_or_none()
	if not mod: abort(400)

	g.db.delete(mod)

	send_repeatable_notification(uid, f"You have been removed as a mod from /s/{sub}")

	g.db.commit()
	
	return redirect(f'/s/{sub}/mods')


@app.get("/create_sub")
@is_not_permabanned
def create_sub(v):
	return render_template("sub/create_sub.html", v=v)


@app.post("/create_sub")
@is_not_permabanned
def create_sub2(v):
	name = request.values.get('name')
	if not name: abort(400)
	name = name.strip().lower()

	if not re.fullmatch(valid_sub_regex, name):
		return render_template("sub/create_sub.html", v=v, error="Sub name not allowed."), 400

	sub = g.db.query(Sub).filter_by(name=name).one_or_none()
	if not sub:
		cost = v.subs_created * 25
		if v.coins < cost:
			return render_template("sub/create_sub.html", v=v, error="You don't have enough coins!"), 403

		v.coins -= cost
		v.subs_created += 1
		g.db.add(v)

		sub = Sub(name=name)
		g.db.add(sub)
		mod = Mod(user_id=v.id, sub=sub.name, created_utc=int(time.time()))
		g.db.add(mod)
		g.db.commit()

	return redirect(f'/s/{sub.name}')

@app.post("/kick/<pid>")
@is_not_permabanned
def kick(v, pid):
	try: pid = int(pid)
	except: abort(400)

	post = get_post(pid)

	if not post.sub: abort(403)
	if not v.mods(post.sub): abort(403)

	post.sub = 'general'
	g.db.add(post)
	g.db.commit()

	cache.delete_memoized(frontlist)

	return {"message": "Post kicked successfully!"}


@app.get('/s/<sub>/settings')
@is_not_permabanned
def sub_settings(v, sub):
	sub = g.db.query(Sub).filter_by(name=sub.strip().lower()).one_or_none()
	if not sub: abort(404)

	if not v.mods(sub.name): abort(403)

	return render_template('sub/settings.html', v=v, sidebar=sub.sidebar, sub=sub)


@app.post('/s/<sub>/sidebar')
@limiter.limit("1/second;30/minute;200/hour;1000/day")
@is_not_permabanned
def post_sub_sidebar(v, sub):
	sub = g.db.query(Sub).filter_by(name=sub.strip().lower()).one_or_none()
	if not sub: abort(404)
	
	if not v.mods(sub.name): abort(403)

	sub.sidebar = request.values.get('sidebar', '').strip()[:500]
	sub.sidebar_html = sanitize(sub.sidebar)
	if len(sub.sidebar_html) > 1000: return "Sidebar is too big!"

	g.db.add(sub)

	g.db.commit()

	return redirect(f'/s/{sub.name}/settings')


@app.post('/s/<sub>/css')
@limiter.limit("1/second;30/minute;200/hour;1000/day")
@is_not_permabanned
def post_sub_css(v, sub):
	sub = g.db.query(Sub).filter_by(name=sub.strip().lower()).one_or_none()
	if not sub: abort(404)
	
	if not v.mods(sub.name): abort(403)

	sub.css = request.values.get('css', '').strip()
	g.db.add(sub)

	g.db.commit()

	return redirect(f'/s/{sub.name}/settings')


@app.get("/s/<sub>/css")
def get_sub_css(sub):
	sub = g.db.query(Sub).filter_by(name=sub.strip().lower()).one_or_none()
	if not sub: abort(404)
	resp=make_response(sub.css or "")
	resp.headers.add("Content-Type", "text/css")
	return resp

@app.post("/s/<sub>/banner")
@limiter.limit("1/second;10/day")
@is_not_permabanned
def sub_banner(v, sub):
	if v and v.patron:
		if request.content_length > 8 * 1024 * 1024: return {"error":"Max file size is 8 MB."}, 413
	elif request.content_length > 4 * 1024 * 1024: return {"error":"Max file size is 4 MB."}, 413

	if request.headers.get("cf-ipcountry") == "T1": return {"error":"Image uploads are not allowed through TOR."}, 403

	sub = g.db.query(Sub).filter_by(name=sub.lower().strip()).one_or_none()
	if not sub: abort(404)

	if not v.mods(sub.name): abort(403)

	file = request.files["banner"]

	name = f'/images/{time.time()}'.replace('.','')[:-5] + '.webp'
	file.save(name)
	bannerurl = process_image(name)

	if bannerurl:
		if sub.bannerurl and '/images/' in sub.bannerurl:
			fpath = '/images/' + sub.bannerurl.split('/images/')[1]
			if path.isfile(fpath): os.remove(fpath)
		sub.bannerurl = bannerurl
		g.db.add(sub)
		g.db.commit()

	return redirect(f'/s/{sub.name}/settings')

@app.post("/s/<sub>/sidebar_image")
@limiter.limit("1/second;10/day")
@is_not_permabanned
def sub_sidebar(v, sub):
	if v and v.patron:
		if request.content_length > 8 * 1024 * 1024: return {"error":"Max file size is 8 MB."}, 413
	elif request.content_length > 4 * 1024 * 1024: return {"error":"Max file size is 4 MB."}, 413

	if request.headers.get("cf-ipcountry") == "T1": return {"error":"Image uploads are not allowed through TOR."}, 403

	sub = g.db.query(Sub).filter_by(name=sub.lower().strip()).one_or_none()
	if not sub: abort(404)

	if not v.mods(sub.name): abort(403)
	
	file = request.files["sidebar"]
	name = f'/images/{time.time()}'.replace('.','')[:-5] + '.webp'
	file.save(name)
	sidebarurl = process_image(name)

	if sidebarurl:
		if sub.sidebarurl and '/images/' in sub.sidebarurl:
			fpath = '/images/' + sub.sidebarurl.split('/images/')[1]
			if path.isfile(fpath): os.remove(fpath)
		sub.sidebarurl = sidebarurl
		g.db.add(sub)
		g.db.commit()

	return redirect(f'/s/{sub.name}/settings')
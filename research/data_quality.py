def check_availability(domains):
    res = []
    for d in domains:
        d = d.strip()
        url = f"{'http://' if not d.startswith('http') else ''}{d}/app-ads.txt"
        try:
            r = requests.get(url, timeout=10)
            status = 'Доступен' if r.status_code == 200 else f'HTTP {r.status_code}'
            content = r.text if r.status_code == 200 else None
        except requests.exceptions.Timeout:
            status, content = 'Timeout', None
        except:
            status, content = 'Сетевая ошибка', None
        res.append({'domain': d, 'ads_status': status, 'content': content})
    return pd.DataFrame(res)

def check_tables_nulls(df_pages, df_funnel, df_users):
    configs = {
        'Pages': (df_pages, ['partner_id', 'partner_login', 'manager']),
        'Funnel': (df_funnel, ['page_tac_last_30_days', 'app']),
        'Users': (df_users, ['id', 'email'])}
    for name, (df, cols) in configs.items():
        if not df.empty:
            print(df[cols].isnull().sum())
    if not df_funnel.empty:
        revenue = pd.to_numeric(df_funnel['page_tac_last_30_days'], errors='coerce').fillna(0)
        active_partners = (revenue > 0).sum()
        share = active_partners / len(df_funnel)


def check_quality_consistency(df_p, df_f, df_u):
    def norm(s): 
        return s.dropna().astype(str).str.replace(r'\.0$$', '', regex=True).str.strip()
    pk_rate = (df_p['page_id'].nunique() / len(df_p) * 100) if not df_p.empty else 0
    # связь Funnel -> Pages
    funnel_rate = 0
    if not df_p.empty and not df_f.empty:
        p_ids = set(norm(df_p['page_id']))
        f_ids = norm(df_f['page_id'])
        funnel_rate = (f_ids.isin(p_ids).sum() / len(f_ids) * 100) if len(f_ids) else 0
    # связь Pages -> Users
    users_rate = 0
    if not df_p.empty and not df_u.empty:
        p_parts = set(norm(df_p['partner_id']))
        u_ids = set(norm(df_u['id']))
        if p_parts:
            users_rate = (len(p_parts & u_ids) / len(p_parts) * 100)
    return pk_rate, funnel_rate, users_rate

def check_quality_fitness(df_f, refs):
    iab_rate = 0
    pat = re.compile(r'^[^,]+,\s*[^,]+,\s*(DIRECT|RESELLER)(,\s*[^,]+)?$$', re.IGNORECASE)
    
    if refs: 
        matches = sum(1 for l in refs if pat.match(l))
        iab_rate = (matches / len(refs) * 100)

    rev_rate = 0
    if not df_f.empty and 'page_tac_last_30_days' in df_f.columns:
        revenue = pd.to_numeric(df_f['page_tac_last_30_days'], errors='coerce').fillna(0)
        rev_rate = (revenue > 0).mean() * 100
        
    return iab_rate, rev_rate


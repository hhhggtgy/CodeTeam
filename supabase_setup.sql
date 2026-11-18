-- ============================================================
-- CodeTeam DevTools: рейтинг, друзья, уведомления, админ-статистика
-- Вставь весь файл в Supabase: SQL Editor -> New query -> Run
-- ============================================================

-- 1. ТАБЛИЦЫ ---------------------------------------------------
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  nick text not null check (char_length(nick) between 2 and 16
        and lower(nick) !~ '(админ|admin|модер|moder)'),
  avatar text not null default '🦊' check (char_length(avatar) <= 8),
  code text not null unique,
  points int not null default 0 check (points between 0 and 100000),
  tools int not null default 0 check (tools between 0 and 100),
  projects int not null default 0 check (projects between 0 and 100),
  cmds int not null default 0 check (cmds between 0 and 100000),
  achievements int not null default 0 check (achievements between 0 and 100),
  hidden boolean not null default false,
  created_at timestamptz not null default now(),
  last_seen timestamptz not null default now()
);
create unique index profiles_nick_lower on public.profiles (lower(nick));

create table public.friendships (
  id bigint generated always as identity primary key,
  requester uuid not null references public.profiles(id) on delete cascade,
  addressee uuid not null references public.profiles(id) on delete cascade,
  status text not null default 'pending' check (status in ('pending','accepted')),
  created_at timestamptz not null default now(),
  unique (requester, addressee),
  check (requester <> addressee)
);

create table public.notifications (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  kind text not null,
  text text not null,
  read boolean not null default false,
  created_at timestamptz not null default now()
);

create table public.events (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  kind text not null check (kind in ('tool','proj')),
  name text not null check (char_length(name) <= 40),
  created_at timestamptz not null default now()
);

create table public.admins (user_id uuid primary key references auth.users(id) on delete cascade);

-- 2. ФУНКЦИИ ---------------------------------------------------
create function public.is_admin() returns boolean
language sql security definer stable set search_path = public as
$$ select exists (select 1 from public.admins where user_id = auth.uid()) $$;

create function public.get_my_code() returns text
language sql security definer stable set search_path = public as
$$ select code from public.profiles where id = auth.uid() $$;

create function public.find_by_code(c text)
returns table (id uuid, nick text, avatar text)
language sql security definer stable set search_path = public as
$$ select p.id, p.nick, p.avatar from public.profiles p
   where p.code = upper(trim(c)) and not p.hidden and p.id <> auth.uid() limit 1 $$;

create function public.admin_set_hidden(pid uuid, h boolean) returns void
language plpgsql security definer set search_path = public as
$$ begin
  if not public.is_admin() then raise exception 'нет доступа'; end if;
  update public.profiles set hidden = h where id = pid;
end $$;

create function public.admin_delete_profile(pid uuid) returns void
language plpgsql security definer set search_path = public as
$$ begin
  if not public.is_admin() then raise exception 'нет доступа'; end if;
  delete from auth.users where id = pid;
end $$;

create function public.delete_me() returns void
language sql security definer set search_path = public as
$$ delete from auth.users where id = auth.uid() $$;

create function public.notify_friend() returns trigger
language plpgsql security definer set search_path = public as
$$ begin
  if tg_op = 'INSERT' then
    insert into public.notifications(user_id, kind, text)
    select new.addressee, 'friend_request',
           (select nick from public.profiles where id = new.requester) || ' хочет дружить';
  elsif tg_op = 'UPDATE' and new.status = 'accepted' and old.status = 'pending' then
    insert into public.notifications(user_id, kind, text)
    select new.requester, 'friend_accept',
           (select nick from public.profiles where id = new.addressee) || ' принял(а) заявку в друзья';
  end if;
  return new;
end $$;
create trigger trg_friend after insert or update on public.friendships
  for each row execute function public.notify_friend();

-- 3. ДОСТУП (RLS) ----------------------------------------------
alter table public.profiles      enable row level security;
alter table public.friendships   enable row level security;
alter table public.notifications enable row level security;
alter table public.events        enable row level security;
alter table public.admins        enable row level security;

revoke all on public.profiles, public.friendships, public.notifications,
              public.events, public.admins from anon, authenticated;

-- код друга (code) нельзя прочитать напрямую: только свой через get_my_code()
grant select (id, nick, avatar, points, tools, projects, cmds, achievements,
              hidden, created_at, last_seen) on public.profiles to authenticated;
grant insert (id, nick, avatar, code, points, tools, projects, cmds, achievements)
      on public.profiles to authenticated;
grant update (nick, avatar, points, tools, projects, cmds, achievements, last_seen)
      on public.profiles to authenticated;
grant select, insert, delete on public.friendships to authenticated;
grant update (status) on public.friendships to authenticated;
grant select on public.notifications to authenticated;
grant update (read) on public.notifications to authenticated;
grant select on public.events to authenticated;
grant insert (user_id, kind, name) on public.events to authenticated;

create policy profiles_select on public.profiles for select to authenticated
  using (not hidden or id = auth.uid() or public.is_admin());
create policy profiles_insert on public.profiles for insert to authenticated
  with check (id = auth.uid());
create policy profiles_update on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

create policy fr_select on public.friendships for select to authenticated
  using (requester = auth.uid() or addressee = auth.uid());
create policy fr_insert on public.friendships for insert to authenticated
  with check (requester = auth.uid() and status = 'pending');
create policy fr_update on public.friendships for update to authenticated
  using (addressee = auth.uid()) with check (addressee = auth.uid() and status = 'accepted');
create policy fr_delete on public.friendships for delete to authenticated
  using (requester = auth.uid() or addressee = auth.uid());

create policy nt_select on public.notifications for select to authenticated
  using (user_id = auth.uid());
create policy nt_update on public.notifications for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy ev_insert on public.events for insert to authenticated
  with check (user_id = auth.uid());
create policy ev_select on public.events for select to authenticated
  using (public.is_admin());

revoke execute on all functions in schema public from public, anon;
grant  execute on all functions in schema public to authenticated;

-- 4. АДМИН -----------------------------------------------------
-- Сначала создай пользователя: Authentication -> Users -> Add user (email и пароль).
-- Потом выполни, подставив СВОЙ email:
-- insert into public.admins(user_id) select id from auth.users where email = 'ТВОЙ_EMAIL';

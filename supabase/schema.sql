create table if not exists profiles (
  id uuid primary key,
  email text,
  full_name text,
  plan text default 'free',
  ai_credits integer not null default 100,
  last_login_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid unique references profiles(id) on delete cascade,
  stripe_customer_id text,
  stripe_subscription_id text unique,
  stripe_price_id text,
  status text not null default 'inactive',
  current_period_end timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists command_logs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references profiles(id) on delete cascade,
  command_type text not null,
  prompt text not null,
  output text,
  status text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists ai_generations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references profiles(id) on delete cascade,
  model text not null,
  prompt text not null,
  output text not null,
  credits_used integer not null default 1,
  created_at timestamptz not null default now()
);

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  key text unique not null,
  name text not null,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists stripe_events (
  id uuid primary key default gen_random_uuid(),
  event_id text unique not null,
  event_type text not null,
  processed_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

insert into projects (key, name, status)
values
  ('sc-aic-prime', 'SC-AIC Prime', 'active'),
  ('forgemind-x', 'ForgeMind X', 'active'),
  ('ai-security', 'AI Security System', 'active'),
  ('ai-music', 'AI Music Empire', 'active')
on conflict (key) do update set
  name = excluded.name,
  status = excluded.status,
  updated_at = now();

create or replace function decrement_ai_credits(target_user_id uuid, used_credits integer)
returns void
language plpgsql
security definer
as $$
begin
  update profiles
  set ai_credits = greatest(coalesce(ai_credits, 0) - coalesce(used_credits, 0), 0),
      updated_at = now()
  where id = target_user_id;
end;
$$;

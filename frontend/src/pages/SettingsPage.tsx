import { Button, Input, Tag } from 'antd';
import { ProfileCard } from '../components/ProfileCard';
import { FieldHelp } from '../components/FieldHelp';
import 'dayjs/locale/ru';
import { Bell, ChevronRight, ShieldCheck, Sparkles, Users } from 'lucide-react';

import type { WorkspaceView } from '../App';
export function SettingsPage({ workspace }: { workspace: WorkspaceView }) {
	const {
		session,
		setPage,
		busy,
		aiKey,
		setAiKey,
		aiModel,
		setAiModel,
		isAdmin,
		loadUsers,
		connectAI,
	} = workspace;
	return (
		<>
			<div className="page-title">
				<div>
					<span className="overline">{session.user.name}</span>
					<h1>Настройки</h1>
				</div>
				<span className="profile-badge">
					{isAdmin ? <ShieldCheck size={20} /> : <Users size={20} />}
				</span>
			</div>
			{isAdmin && (
				<button
					className="settings-menu"
					onClick={() => {
						void loadUsers();
						setPage('team');
					}}
				>
					<span className="settings-icon">
						<Users size={21} />
					</span>
					<span>
						<b>Команда и доступ</b>
						<small>Мастера, Telegram ID и роли</small>
					</span>
					<ChevronRight size={18} />
				</button>
			)}
			{isAdmin && (
				<button className="settings-menu" onClick={() => setPage('reminders')}>
					<span className="settings-icon reminder-icon">
						<Bell size={21} />
					</span>
					<span>
						<b>Напоминания мастерам</b>
						<small>Сообщения в Telegram и расписание</small>
					</span>
					<ChevronRight size={18} />
				</button>
			)}
			{isAdmin && (
				<details className="settings-card admin-settings-details">
					<summary>
						<Sparkles size={20} />
						<b>Умный подбор</b>
						<Tag color={session.ai_connected ? 'green' : 'gold'}>
							{session.ai_connected ? 'Подключён' : 'Нужен ключ'}
						</Tag>
					</summary>
					<label>Модель</label>
					<Input value={aiModel} onChange={(e) => setAiModel(e.target.value)} />
					<label>
						Ключ API <FieldHelp topic="ai" />
					</label>
					<Input.Password
						value={aiKey}
						onChange={(e) => setAiKey(e.target.value)}
						placeholder={session.ai_connected ? 'Настроен · введите для замены' : 'Ключ DeepSeek'}
						autoComplete="off"
					/>
					<Button type="primary" block disabled={!aiKey.trim()} loading={busy} onClick={connectAI}>
						Подключить
					</Button>
				</details>
			)}
			<ProfileCard workspace={workspace} />
		</>
	);
}

import { Button, Input, Tag } from 'antd';
import { ProfileCard } from '../components/ProfileCard';
import { ProfileWebhooks } from '../components/ProfileWebhooks';
import { FieldHelp } from '../components/FieldHelp';
import 'dayjs/locale/ru';
import { Bell, ChevronRight, Sparkles, Users } from 'lucide-react';
import { useId } from 'react';

import type { WorkspaceView } from '../App';
export function SettingsPage({ workspace }: { workspace: WorkspaceView }) {
	const aiKeyFieldId = useId();
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
				<h1>Настройки</h1>
			</div>
			<ProfileCard workspace={workspace} />
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
					<div className="help-field-heading">
						<label htmlFor={aiKeyFieldId}>Ключ API</label>
						<FieldHelp topic="ai" />
					</div>
					<Input.Password
						id={aiKeyFieldId}
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
			{!isAdmin && <ProfileWebhooks workspace={workspace} />}
		</>
	);
}

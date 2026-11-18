import { Input } from '../components/Input';
import { Button } from '../components/Button';
import { ProfileCard } from '../components/ProfileCard';
import { ProfileWebhooks } from '../components/ProfileWebhooks';
import { FieldHelp } from '../components/FieldHelp';
import 'dayjs/locale/ru';
import { Sparkles, Users } from 'lucide-react';
import { Bell, ChevronRight } from '../components/kit-icons';
import { useId } from 'react';
import type { useTelegramNotifications } from '../hooks/useTelegramNotifications';

import type { WorkspaceView } from '../App';
import { TableNotifications, type useTableNotifications } from './TableNotifications';
export function SettingsPage({
	workspace,
	notifications,
	tableInbox,
}: {
	workspace: WorkspaceView;
	notifications: ReturnType<typeof useTelegramNotifications>;
	tableInbox: ReturnType<typeof useTableNotifications>;
}) {
	const aiKeyFieldId = useId();
	const aiModelFieldId = useId();
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
			<TableNotifications key={session.user.role} workspace={workspace} inbox={tableInbox} />
			{notifications.supported && !notifications.granted && (
				<button
					className="settings-menu"
					disabled={notifications.requesting}
					onClick={notifications.requestPermission}
				>
					<span className="settings-icon">
						<Bell size={21} />
					</span>
					<span>
						<b>Разрешить уведомления</b>
						<small>Сообщения от бота в Telegram</small>
					</span>
					<ChevronRight size={18} />
				</button>
			)}
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
					<span className="settings-icon">
						<Bell size={21} />
					</span>
					<span>
						<b>Уведомления</b>
						<small>Сообщения в Telegram и расписание</small>
					</span>
					<ChevronRight size={18} />
				</button>
			)}
			{isAdmin && (
				<details className="settings-card admin-settings-details">
					<summary className="settings-menu">
						<span className="settings-icon">
							<Sparkles size={21} />
						</span>
						<span>
							<b>Умный подбор</b>
							<small>{session.ai_connected ? 'Подключён' : 'Нужен ключ'}</small>
						</span>
						<ChevronRight size={18} />
					</summary>
					<label htmlFor={aiModelFieldId}>Модель</label>
					<Input id={aiModelFieldId} value={aiModel} onChange={(e) => setAiModel(e.target.value)} />
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

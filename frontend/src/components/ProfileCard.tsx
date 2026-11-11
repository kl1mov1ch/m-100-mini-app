import { App, Button, Input, Tag } from 'antd';
import { Pencil } from 'lucide-react';
import { useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import { RoleSwitch } from './RoleSwitch';
import { TelegramAvatar } from './TelegramAvatar';

export function ProfileCard({ workspace }: { workspace: WorkspaceView }) {
	const { session } = workspace;
	const { message } = App.useApp();
	const [name, setName] = useState(session.user.name);
	const [busy, setBusy] = useState(false);
	const [editing, setEditing] = useState(false);
	const trimmedName = name.trim();
	const changed = trimmedName !== session.user.name;
	const save = async () => {
		if (!trimmedName || !changed || busy) return;
		setBusy(true);
		try {
			await request('/profile', { name: trimmedName });
			await workspace.refresh(true);
			setEditing(false);
			message.success('Имя сохранено');
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setBusy(false);
		}
	};
	return (
		<section className="settings-card profile-settings">
			<div className="profile-intro">
				<TelegramAvatar
					userId={session.user.telegram_id}
					name={session.user.name}
					source={session.user.avatar_url}
					size={46}
				/>
				<div>
					<b>{session.user.name}</b>
					<div className="profile-meta">
						{session.user.username && <small>@{session.user.username}</small>}
						<Tag color={workspace.isAdmin ? 'blue' : 'green'}>
							{workspace.isAdmin ? 'Администратор' : 'Мастер'}
						</Tag>
					</div>
				</div>
				<Button
					type="text"
					aria-label="Изменить имя"
					title="Изменить имя"
					icon={<Pencil size={17} />}
					disabled={editing}
					onClick={() => {
						setName(session.user.name);
						setEditing(true);
					}}
				/>
			</div>
			{editing && (
				<form
					className="profile-name-form"
					onSubmit={(event) => {
						event.preventDefault();
						void save();
					}}
				>
					<label htmlFor="profile-name">Имя в приложении</label>
					<Input
						id="profile-name"
						value={name}
						onChange={(event) => setName(event.target.value)}
						maxLength={100}
						disabled={busy}
					/>
					<div className="profile-name-actions">
						<Button disabled={busy} onClick={() => setEditing(false)}>
							Отмена
						</Button>
						<Button
							type="primary"
							htmlType="submit"
							loading={busy}
							disabled={!trimmedName || !changed}
						>
							Сохранить
						</Button>
					</div>
				</form>
			)}
			{session.can_switch_role && (
				<div className="profile-test-role">
					<span>Режим тестирования</span>
					<RoleSwitch workspace={workspace} unsaved={editing && changed} />
				</div>
			)}
		</section>
	);
}

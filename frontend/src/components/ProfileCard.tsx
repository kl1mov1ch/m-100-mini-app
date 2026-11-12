import { App, Button, Input, Tag } from 'antd';
import { Check, Pencil, X } from 'lucide-react';
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
					size={40}
				/>
				{editing ? (
					<form
						className="profile-name-form"
						onSubmit={(event) => {
							event.preventDefault();
							void save();
						}}
						onKeyDown={(event) => {
							if (event.key === 'Escape' && !busy) setEditing(false);
						}}
					>
						<Input
							aria-label="Имя в приложении"
							autoFocus
							value={name}
							onChange={(event) => setName(event.target.value)}
							maxLength={100}
							disabled={busy}
						/>
						<Button
							type="text"
							aria-label="Отменить редактирование имени"
							title="Отмена"
							icon={<X size={18} />}
							disabled={busy}
							onClick={() => setEditing(false)}
						/>
						<Button
							type="text"
							htmlType="submit"
							aria-label="Сохранить имя"
							title="Сохранить"
							className="profile-name-save"
							icon={<Check size={19} />}
							loading={busy}
							disabled={!trimmedName || !changed}
						/>
					</form>
				) : (
					<>
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
							className="profile-name-edit"
							aria-label="Изменить имя"
							title="Изменить имя"
							icon={<Pencil size={17} />}
							onClick={() => {
								setName(session.user.name);
								setEditing(true);
							}}
						/>
					</>
				)}
			</div>
			{session.can_switch_role && (
				<div className="profile-test-role">
					<span>Режим тестирования</span>
					<RoleSwitch workspace={workspace} unsaved={editing && changed} />
				</div>
			)}
		</section>
	);
}

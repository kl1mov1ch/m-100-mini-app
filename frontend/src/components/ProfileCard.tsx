import { App, Button, Input } from 'antd';
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
	const save = async () => {
		setBusy(true);
		try {
			await request('/profile', { name });
			await workspace.refresh(true);
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
					size={52}
				/>
				<div>
					<b>{session.user.name}</b>
					<small>{session.user.username ? '@' + session.user.username : 'Профиль Telegram'}</small>
				</div>
			</div>
			<label htmlFor="profile-name">Ваше имя в приложении</label>
			<Input
				id="profile-name"
				value={name}
				onChange={(event) => setName(event.target.value)}
				maxLength={100}
			/>
			<Button
				block
				onClick={save}
				loading={busy}
				disabled={!name.trim() || name === session.user.name}
			>
				Сохранить имя
			</Button>
			<RoleSwitch workspace={workspace} unsaved={name !== session.user.name} />
		</section>
	);
}

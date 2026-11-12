import { App, Button, Input } from 'antd';
import { KeyRound } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import type { WorkspaceView } from '../App';
import { FieldHelp } from './FieldHelp';

export function ProfileWebhooks({ workspace }: { workspace: WorkspaceView }) {
	const [name, setName] = useState('');
	const [url, setUrl] = useState('');
	const [saving, setSaving] = useState(false);
	const { message } = App.useApp();

	const save = async (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		if (!url.trim() || saving) return;
		setSaving(true);
		try {
			await workspace.saveDiskWebhook({ name, url });
			setName('');
			setUrl('');
			message.success('Вебхук сохранён в профиле');
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setSaving(false);
		}
	};

	return (
		<section className="settings-card profile-webhooks">
			<h2>
				<KeyRound size={18} /> Вебхуки Битрикс24 <FieldHelp topic="bitrix" />
			</h2>
			{workspace.diskWebhooks.length > 0 && (
				<ul>
					{workspace.diskWebhooks.map(({ id, name, portal }) => (
						<li key={id}>
							<strong>{name}</strong>
							{portal !== name && <small>{portal}</small>}
						</li>
					))}
				</ul>
			)}
			<form className="object-connection-form" onSubmit={save}>
				<label>
					Название
					<Input
						value={name}
						maxLength={80}
						placeholder="Например, Рабочий портал"
						onChange={(event) => setName(event.target.value)}
					/>
				</label>
				<label>
					Вебхук с правом «Диск»
					<Input.Password
						value={url}
						maxLength={500}
						placeholder="https://ваш-портал.bitrix24.by/rest/…"
						autoComplete="new-password"
						onChange={(event) => setUrl(event.target.value)}
					/>
				</label>
				<Button type="primary" htmlType="submit" loading={saving} disabled={!url.trim()}>
					Сохранить вебхук
				</Button>
			</form>
		</section>
	);
}

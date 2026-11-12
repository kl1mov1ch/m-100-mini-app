import { Button, Tag } from 'antd';
import { ExternalLink, RefreshCw } from 'lucide-react';
import type { WorkspaceView } from '../App';
import dayjs from '../lib/date';
import { openExternalLink } from '../lib/telegram';

export function ObjectTableCard({ workspace }: { workspace: WorkspaceView }) {
	const {
		data,
		active,
		positions,
		checkingConnection,
		checkConnection,
		reviewBitrixChanges,
		busy,
	} = workspace;
	if (!data || !active || data.project?.id !== active.id || data.config.source !== 'bitrix')
		return null;
	const config = data.config;
	const check = config.connection_check;
	const original = config.detail_url || config.public_url;
	return (
		<section className="object-table-card">
			<div className="object-table-card-top">
				<div>
					<b>{config.source_name}</b>
					<small>{positions.length} работ · Битрикс24.Диск</small>
				</div>
				<Tag color={config.has_webhook ? 'green' : 'gold'}>
					{config.has_webhook ? 'Подключена' : 'Только чтение'}
				</Tag>
			</div>
			{check && (
				<div
					className={
						'table-check-result ' +
						(!check.reachable ? 'failed' : check.issues.length ? 'has-issues' : 'success')
					}
				>
					<b>{check.message}</b>
					{!check.issues.length && (
						<span>{dayjs(check.checked_at).format('D MMMM, HH:mm')} · Минск</span>
					)}
					{check.reachable && check.issues.length > 0 && (
						<>
							<span>
								{[
									check.issues[0].sheet,
									check.issues[0].affected_rows?.length
										? `столбец ${check.issues[0].column}`
										: check.issues[0].cell,
								]
									.filter(Boolean)
									.join(' · ')}
								{check.issues.length > 1 && ` · ещё ${check.issues.length - 1}`}
							</span>
							<Button size="small" onClick={reviewBitrixChanges} loading={busy}>
								Исправить
							</Button>
						</>
					)}
				</div>
			)}
			<div className="object-table-card-actions">
				<Button
					loading={checkingConnection}
					icon={<RefreshCw size={15} />}
					onClick={checkConnection}
				>
					Проверить соединение
				</Button>
				{original && (
					<Button
						href={original}
						onClick={(event) => openExternalLink(event, original)}
						target="_blank"
						rel="noreferrer"
						icon={<ExternalLink size={15} />}
					>
						Открыть таблицу
					</Button>
				)}
			</div>
		</section>
	);
}

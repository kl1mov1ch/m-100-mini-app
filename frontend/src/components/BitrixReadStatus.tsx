import { Button, Tag } from 'antd';
import { RefreshCw } from 'lucide-react';
import type { WorkspaceView } from '../App';
import dayjs from '../lib/date';

export function BitrixReadStatus({ workspace }: { workspace: WorkspaceView }) {
	const { data, readingBitrix, refreshBitrix } = workspace;
	if (data?.config.source !== 'bitrix') return null;
	const read = data.config.bitrix_read;
	const updatedAt = read?.updated_at || data.config.last_import;
	return (
		<div className="bitrix-read-status">
			<div>
				{read?.status === 'unavailable' ? (
					<Tag color="gold">Битрикс24 недоступен · сохранённые данные</Tag>
				) : read?.status === 'review' ? (
					<Tag color="gold">Есть различия с Битрикс24</Tag>
				) : (
					<Tag color={read ? 'green' : 'default'}>Битрикс24</Tag>
				)}
				{updatedAt && <small>{dayjs(updatedAt).format('D MMM, HH:mm')}</small>}
			</div>
			<Button
				type="text"
				size="small"
				title="Обновить данные Битрикс24"
				aria-label="Обновить данные Битрикс24"
				loading={readingBitrix}
				icon={<RefreshCw size={15} />}
				onClick={() => void refreshBitrix(true)}
			/>
		</div>
	);
}

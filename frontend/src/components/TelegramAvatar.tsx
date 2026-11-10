import { useEffect, useState } from 'react';
import { headers } from '../lib/api';

type TelegramAvatarProps = {
	userId: string;
	name: string;
	source?: string;
	size?: number;
};

export function TelegramAvatar({ userId, name, source, size = 40 }: TelegramAvatarProps) {
	const [image, setImage] = useState(source || '');

	useEffect(() => {
		const controller = new AbortController();
		let objectUrl = '';
		setImage(source || '');

		const loadAvatar = async () => {
			try {
				const response = await fetch('/api/profile/avatar?user_id=' + encodeURIComponent(userId), {
					headers: headers(),
					signal: controller.signal,
				});
				if (!response.ok) return;
				const photo = await response.blob();
				if (controller.signal.aborted) return;
				objectUrl = URL.createObjectURL(photo);
				setImage(objectUrl);
			} catch {
				if (!controller.signal.aborted) setImage(source || '');
			}
		};

		void loadAvatar();
		return () => {
			controller.abort();
			if (objectUrl) URL.revokeObjectURL(objectUrl);
		};
	}, [userId, source]);

	return (
		<span
			className="telegram-avatar"
			style={{ width: size, height: size, minWidth: size, minHeight: size }}
		>
			{image ? (
				<img
					src={image}
					alt={`Аватар ${name}`}
					referrerPolicy="no-referrer"
					onError={() => setImage('')}
				/>
			) : (
				<span role="img" aria-label={`Профиль ${name}`}>
					{name.trim()[0]?.toUpperCase()}
				</span>
			)}
		</span>
	);
}

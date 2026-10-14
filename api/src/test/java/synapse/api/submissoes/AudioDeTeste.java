package synapse.api.submissoes;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

final class AudioDeTeste {

	static byte[] wav() {
		return ByteBuffer.allocate(46)
			.order(ByteOrder.LITTLE_ENDIAN)
			.put("RIFF".getBytes(StandardCharsets.US_ASCII))
			.putInt(38)
			.put("WAVEfmt ".getBytes(StandardCharsets.US_ASCII))
			.putInt(16)
			.putShort((short) 1)
			.putShort((short) 1)
			.putInt(8000)
			.putInt(16000)
			.putShort((short) 2)
			.putShort((short) 16)
			.put("data".getBytes(StandardCharsets.US_ASCII))
			.putInt(2)
			.putShort((short) 0)
			.array();
	}

	static byte[] mp4() {
		return new byte[] { 0, 0, 0, 16, 'f', 't', 'y', 'p', 'M', '4', 'A', ' ', 0, 0, 0, 0, 0, 0, 0, 16, 'm', 'o', 'o',
				'v', 0, 0, 0, 8, 't', 'r', 'a', 'k', 0, 0, 0, 9, 'm', 'd', 'a', 't', 0 };
	}

	static byte[] webm() {
		return new byte[] { 0x1a, 0x45, (byte) 0xdf, (byte) 0xa3, (byte) 0x87, 0x42, (byte) 0x82, (byte) 0x84, 'w', 'e',
				'b', 'm', 0x18, 0x53, (byte) 0x80, 0x67, (byte) 0xff, 0x16, 0x54, (byte) 0xae, 0x6b, (byte) 0x81, 0,
				0x1f, 0x43, (byte) 0xb6, 0x75, (byte) 0x81, 0 };
	}

}

package com.ahuamiao.adcleaner

import android.content.Context
import android.os.Build
import android.provider.Settings
import android.sun.security.x509.AlgorithmId
import android.sun.security.x509.CertificateAlgorithmId
import android.sun.security.x509.CertificateExtensions
import android.sun.security.x509.CertificateIssuerName
import android.sun.security.x509.CertificateSerialNumber
import android.sun.security.x509.CertificateSubjectName
import android.sun.security.x509.CertificateValidity
import android.sun.security.x509.CertificateVersion
import android.sun.security.x509.CertificateX509Key
import android.sun.security.x509.KeyIdentifier
import android.sun.security.x509.PrivateKeyUsageExtension
import android.sun.security.x509.SubjectKeyIdentifierExtension
import android.sun.security.x509.X500Name
import android.sun.security.x509.X509CertImpl
import android.sun.security.x509.X509CertInfo
import io.github.muntashirakon.adb.AbsAdbConnectionManager
import io.github.muntashirakon.adb.android.AdbMdns
import java.io.File
import java.net.InetAddress
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.cert.Certificate
import java.security.cert.CertificateFactory
import java.security.spec.PKCS8EncodedKeySpec
import java.util.Date
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * 内置无线调试（#622）：App 自己配对、自己连本机 adbd 拿 shell 身份，不用装 Shizuku。
 * 做法参考 Mika（github.com/wangzan101/mika）；协议实现用 libadb-android（按 Apache-2.0 使用），
 * 证书生成照它示例 App 的写法。密钥与证书存在 App 私有目录，卸载即删；配对一次后长期有效。
 */
class AdbManager private constructor(context: Context) : AbsAdbConnectionManager() {
    private val keyFile = File(context.filesDir, "adb/key.pk8")
    private val certFile = File(context.filesDir, "adb/cert.der")
    private val privateKey: PrivateKey
    private val certificate: Certificate

    init {
        setApi(Build.VERSION.SDK_INT)
        setTimeout(10, TimeUnit.SECONDS)
        if (keyFile.exists() && certFile.exists()) {
            privateKey = KeyFactory.getInstance("RSA").generatePrivate(PKCS8EncodedKeySpec(keyFile.readBytes()))
            certificate = CertificateFactory.getInstance("X.509").generateCertificate(certFile.inputStream())
        } else {
            val gen = KeyPairGenerator.getInstance("RSA").apply { initialize(2048, SecureRandom()) }
            val pair = gen.generateKeyPair()
            privateKey = pair.private
            val algorithm = "SHA512withRSA"
            val notBefore = Date()
            val notAfter = Date(System.currentTimeMillis() + 100L * 365 * 86400_000L)
            val name = X500Name("CN=AndroidAdCleaner")
            val extensions = CertificateExtensions().apply {
                set("SubjectKeyIdentifier", SubjectKeyIdentifierExtension(KeyIdentifier(pair.public).identifier))
                set("PrivateKeyUsage", PrivateKeyUsageExtension(notBefore, notAfter))
            }
            val info = X509CertInfo().apply {
                set("version", CertificateVersion(2))
                set("serialNumber", CertificateSerialNumber(SecureRandom().nextInt() and Int.MAX_VALUE))
                set("algorithmID", CertificateAlgorithmId(AlgorithmId.get(algorithm)))
                set("subject", CertificateSubjectName(name))
                set("key", CertificateX509Key(pair.public))
                set("validity", CertificateValidity(notBefore, notAfter))
                set("issuer", CertificateIssuerName(name))
                set("extensions", extensions)
            }
            certificate = X509CertImpl(info).apply { sign(privateKey, algorithm) }
            keyFile.parentFile?.mkdirs()
            keyFile.writeBytes(privateKey.encoded)
            certFile.writeBytes(certificate.encoded)
        }
    }

    override fun getPrivateKey(): PrivateKey = privateKey
    override fun getCertificate(): Certificate = certificate
    override fun getDeviceName(): String = "安卓去广告"

    companion object {
        @Volatile private var instance: AdbManager? = null

        fun get(context: Context): AdbManager =
            instance ?: synchronized(this) { instance ?: AdbManager(context.applicationContext).also { instance = it } }

        /** 经 mDNS 找无线调试的某个服务端口（配对 / 连接）；找不到返回 -1。只认本机。 */
        fun discover(context: Context, type: String, timeoutMs: Long): Int {
            val port = AtomicInteger(-1)
            val found = CountDownLatch(1)
            val local = localAddresses()
            val mdns = AdbMdns(context, type) { host: InetAddress?, p: Int ->
                if (host != null && (local.isEmpty() || host.hostAddress in local) && p > 0) {
                    port.set(p)
                    found.countDown()
                }
            }
            mdns.start()
            try {
                found.await(timeoutMs, TimeUnit.MILLISECONDS)
            } finally {
                mdns.stop()
            }
            return port.get()
        }

        /** 本机各网卡的地址：同一个 Wi-Fi 下别人的手机也在广播无线调试，只连自己。 */
        private fun localAddresses(): Set<String> = try {
            java.net.NetworkInterface.getNetworkInterfaces().toList()
                .flatMap { it.inetAddresses.toList() }.mapNotNull { it.hostAddress }.toSet()
        } catch (_: Exception) {
            emptySet()
        }

        /** 无线调试开着吗（设置项 adb_wifi_enabled）。 */
        fun wirelessOn(context: Context): Boolean =
            Settings.Global.getInt(context.contentResolver, "adb_wifi_enabled", 0) == 1

        fun developerOn(context: Context): Boolean =
            Settings.Global.getInt(context.contentResolver, Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) == 1
    }
}

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <span className="text-xl font-semibold text-primary">AI Content Studio</span>
        </div>
        {children}
      </div>
    </div>
  );
}

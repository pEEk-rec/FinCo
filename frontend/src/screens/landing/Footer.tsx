import { Link } from 'react-router';

import { landingCopy } from '../../copy/landing';

export function Footer() {
  return (
    <footer className="w-full bg-[#FBF6F2] py-14 px-6 sm:px-12 lg:px-16 border-t border-[#EADFD7] text-[#1F1A17]">
      <div className="mx-auto max-w-6xl flex flex-col md:flex-row items-start md:items-center justify-between gap-8">
        <div>
          <Link to="/welcome" className="serif-light text-[22px] tracking-tight text-[#1F1A17]">
            FinCo
          </Link>
          <p className="mt-1 text-[13px] text-[#4F4540] max-w-md">{landingCopy.footer.statement}</p>
        </div>

        <div className="flex flex-wrap items-center gap-6 text-[13px] font-medium text-[#4F4540]">
          {landingCopy.footer.links.map((lnk) => (
            <Link key={lnk.href} to={lnk.href} className="hover:text-[#BA3A25] transition-colors">
              {lnk.label}
            </Link>
          ))}
        </div>
      </div>

      <div className="mx-auto max-w-6xl mt-10 pt-6 border-t border-[#EADFD7] flex flex-col sm:flex-row items-center justify-between gap-4 text-[12px] text-[#6B605A]">
        <span>FinCo — Built for students, grounded in calm clarity.</span>
        <span>Zero advertisements · Zero data brokerage</span>
      </div>
    </footer>
  );
}

from crawlers.dir_crawler import main as dir_main
from crawlers.jri_crawler import main as jri_main
from crawlers.mizuho_rt_crawler import main as mizuho_rt_main
from crawlers.mri_crawler import main as mri_main
from crawlers.murc_crawler import main as murc_main
from crawlers.nri_crawler import main as nri_main


def main() -> None:
    mri_main()
    jri_main()
    nri_main()
    dir_main()
    mizuho_rt_main()
    murc_main()


if __name__ == "__main__":
    main()
